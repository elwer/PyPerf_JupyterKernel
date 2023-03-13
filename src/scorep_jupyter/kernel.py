from ipykernel.ipkernel import IPythonKernel
import sys
import os
import ast
import astunparse

PYTHON_EXECUTABLE = sys.executable
userpersistence_token = "scorep_jupyter.userpersistence"
scorep_script_name = "scorep_script.py"
jupyter_dump = "jupyter_dump.pkl"
subprocess_dump = "subprocess_dump.pkl"


class ScorepPythonKernel(IPythonKernel):
    implementation = 'Python and Score-P'
    implementation_version = '1.0'
    language = 'python'
    language_version = '3.8'
    language_info = {
        'name': 'Any text',
        'mimetype': 'text/plain',
        'file_extension': '.py',
    }
    banner = "Jupyter kernel with Score-P Python binding."

    user_persistence = ""
    scorep_binding_args = []
    scorep_env = []

    multicellmode = False
    multicellmode_cellcount = 0
    multicell_code = ""

    writemode = False
    writemode_filename = 'jupyter_to_script'
    writemode_multicell = False

    writemode_scorep_binding_args = []
    writemode_scorep_env = []

    # TODO: reset variables after each finalize writefile?
    bash_script_filename = ""
    python_script_filename = ""
    bash_script = None
    python_script = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def cell_output(self, string, stream='stdout'):
        """
        Display string as cell output.
        """
        stream_content = {'name': stream, 'text': string}
        self.send_response(self.iopub_socket, 'stream', stream_content)

    def standard_reply(self):
        self.shell.execution_count += 1
        return {'status': 'ok',
                'execution_count': self.shell.execution_count - 1,
                'payload': [],
                'user_expressions': {},
                }

    def set_scorep_env(self, code):
        """
        Read and record Score-P environment variables from the cell.
        """
        self.scorep_env += code.split('\n')[1:]
        self.cell_output(
            'Score-P environment set successfully: ' + str(self.scorep_env))
        return self.standard_reply()

    def set_scorep_pythonargs(self, code):
        """
        Read and record Score-P Python binding arguments from the cell.
        """
        self.scorep_binding_args += code.split('\n')[1:]
        self.cell_output(
            'Score-P Python binding arguments set successfully: ' + str(self.scorep_binding_args))
        return self.standard_reply()

    def enable_multicellmode(self):
        # TODO: scorep setup cells are not affected
        self.multicellmode = True
        self.cell_output(
            'Multicell mode enabled. The following cells will be marked for instrumented execution.')
        return self.standard_reply()

    def abort_multicellmode(self):
        self.multicellmode = False
        self.multicell_code = ""
        self.cell_output('Multicell mode aborted.')
        return self.standard_reply()

    def append_multicellmode(self, code):
        self.multicell_code += ("\n" + code)
        self.multicellmode_cellcount += 1
        self.cell_output(
            f'Cell marked for multicell mode. It will be executed at position {self.multicellmode_cellcount}')
        return self.standard_reply()

    def start_writefile(self):
        """
        Start recording the notebook as a Python script. Custom file name
        can be defined as an argument of the magic command.
        """
        # TODO: check for os path existence
        self.writemode = True
        self.bash_script_filename = os.path.realpath(
            '') + '/' + self.writemode_filename + '_run.sh'
        self.python_script_filename = os.path.realpath(
            '') + '/' + self.writemode_filename + '.py'
        self.bash_script = open(self.bash_script_filename, 'w+')
        self.bash_script.write('# This bash script is generated automatically to run\n' +
                               '# Jupyter Notebook -> Python script convertation by Score-P kernel\n' +
                               '# ' + self.python_script_filename + '\n')
        self.bash_script.write('#!/bin/bash\n')
        self.python_script = open(self.python_script_filename, 'w+')
        self.python_script.write('# This is the automatic Jupyter Notebook -> Python script convertation by Score-P kernel.\n' +
                                 '# Code corresponding to the cells not marked for Score-P instrumentation\n' +
                                 '# is framed "with scorep.instrumenter.disable()".\n' +
                                 '# The script can be run with proper settings with bash script\n' +
                                 '# ' + self.bash_script_filename + '\n')
        # import scorep by default, convertation might add scorep commands
        # not present in original notebook (e.g. cells without instrumentation)
        self.python_script.write('import scorep\n')

        self.cell_output('Started converting to Python script. See files:\n' +
                         self.bash_script_filename + '\n' + self.python_script_filename + '\n')
        return self.standard_reply()

    def end_writefile(self):
        """
        Finish recording the notebook as a Python script.
        """
        # TODO: check for os path existence
        self.writemode = False
        self.bash_script.write(
            f"{' '.join(self.writemode_scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.writemode_scorep_binding_args)} {self.python_script_filename}")

        self.bash_script.close()
        self.python_script.close()
        self.cell_output('Finished converting to Python script, files closed.')
        return self.standard_reply()

    def append_writefile(self, code):
        if code.startswith('%%scorep_env'):
            self.writemode_scorep_env += code.split('\n')[1:]
            self.cell_output('Environment variables recorded.')
        elif code.startswith('%%scorep_python_binding_arguments'):
            self.writemode_scorep_binding_args += code.split('\n')[1:]
            self.cell_output('Score-P bindings arguments recorded.')

        elif code.startswith('%%enable_multicellmode'):
            self.writemode_multicell = True
        elif code.startswith('%%finalize_multicellmode'):
            self.writemode_multicell = False
        elif code.startswith('%%abort_multicellmode'):
            self.cell_output(
                'Multicell abort command is ignored in write mode, check if the output file is recorded as expected.')

        elif code.startswith('%%execute_with_scorep') or self.writemode_multicell:
            # cut all magic commands
            code = code.split('\n')
            code = ''.join(
                [line + '\n' for line in code if not line.startswith('%%')])
            self.python_script.write(code + '\n')
            self.cell_output(
                'Python commands with instrumentation recorded.')

        elif not self.writemode_multicell:
            # cut all magic commands
            code = code.split('\n')
            code = ''.join(
                ['    ' + line + '\n' for line in code if not line.startswith('%%')])
            self.python_script.write(
                'with scorep.instrumenter.disable():\n' + code + '\n')
            self.cell_output(
                'Python commands without instrumentation recorded.')
        return self.standard_reply()

    def save_definitions(self, code):
        """
        Extract imported modules and definitions of classes and functions from the code block.
        """
        # can't use in kernel as import from userpersistence:
        # self-reference error during dill dump of notebook
        root = ast.parse(code)
        definitions = []
        for top_node in ast.iter_child_nodes(root):
            if isinstance(top_node, ast.With):
                for node in ast.iter_child_nodes(top_node):
                    if (isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef) or
                            isinstance(node, ast.ClassDef) or isinstance(node, ast.Import) or isinstance(node,
                                                                                                         ast.ImportFrom)):
                        definitions.append(node)
            elif (isinstance(top_node, ast.FunctionDef) or isinstance(top_node, ast.AsyncFunctionDef) or
                  isinstance(top_node, ast.ClassDef) or isinstance(top_node, ast.Import) or isinstance(top_node,
                                                                                                       ast.ImportFrom)):
                definitions.append(top_node)

        pers_string = ""
        for node in definitions:
            pers_string += astunparse.unparse(node)

        return pers_string

    def get_user_variables(self, code):
        """
        Extract user-assigned variables from code. Unlike dir(), nothing coming from the imported modules is included.
        """
        root = ast.parse(code)

        variables = set()
        for node in ast.walk(root):
            # assignment nodes can include attributes, therefore go over all targets and check for attribute nodes
            if isinstance(node, ast.Assign) or isinstance(node, ast.AnnAssign):
                for el in node.targets:
                    for target_node in ast.walk(el):
                        if isinstance(target_node, ast.Name):
                            variables.add(target_node.id)

        return variables

    async def scorep_execute(self, code, silent, store_history=True, user_expressions=None,
                             allow_stdin=False, *, cell_id=None):
        # ghost cell - dump current jupyter session
        dump_jupyter = "import dill\n" + \
                      f"dill.dump_session('{jupyter_dump}')"
        reply_status_dump = await super().do_execute(dump_jupyter, silent, store_history=False,
                                                     user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)

        if reply_status_dump['status'] != 'ok':
            self.shell.execution_count += 1
            reply_status_dump['execution_count'] = self.shell.execution_count - 1
            return reply_status_dump

        # prepare code for the scorep binding instrumented execution
        user_variables = self.get_user_variables(code)

        scorep_code = "import scorep\n" + \
                      "with scorep.instrumenter.disable():\n" + \
                     f"    from {userpersistence_token} import * \n" + \
                      "    import dill\n" + \
                     f"    globals().update(dill.load_module_asdict('{jupyter_dump}'))\n" + \
                      code + "\n" + \
                      "with scorep.instrumenter.disable():\n" + \
                     f"   save_user_variables(globals(), {str(user_variables)}, '{subprocess_dump}')"

        scorep_script_file = open(scorep_script_name, 'w+')
        scorep_script_file.write(scorep_code)
        scorep_script_file.close()

        script_run = "%%bash\n" + \
            f"{' '.join(self.scorep_env)} {PYTHON_EXECUTABLE} -m scorep {' '.join(self.scorep_binding_args)} {scorep_script_name}"
        reply_status_exec = await super().do_execute(script_run, silent, store_history=False,
                                                     user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)

        if reply_status_exec['status'] != 'ok':
            return reply_status_exec

        # ghost cell - load subprocess persistence back to jupyter session
        load_jupyter = self.save_definitions(code) + "\n" + \
                      f"vars_load = open('{subprocess_dump}', 'rb')\n" + \
                       "globals().update(dill.load(vars_load))\n" + \
                       "vars_load.close()"
        reply_status_load = await super().do_execute(load_jupyter, silent, store_history=False,
                                                     user_expressions=user_expressions, allow_stdin=allow_stdin, cell_id=cell_id)

        if reply_status_load['status'] != 'ok':
            self.shell.execution_count += 1
            reply_status_load['execution_count'] = self.shell.execution_count - 1
            return reply_status_load

        folder_arg = next(
            (arg for arg in self.scorep_binding_args if "SCOREP_EXPERIMENT_DIRECTORY" in arg), None)
        if folder_arg:
            scorep_folder = folder_arg.split('=')[-1]
        else:
            scorep_folder = max([d for d in os.listdir('.') if os.path.isdir(
                d) and 'scorep' in d], key=os.path.getmtime)
        self.cell_output(
            f"Instrumentation results can be found in {os.getcwd()}/{scorep_folder}")

        for aux_file in [scorep_script_name, jupyter_dump, subprocess_dump]:
            if os.path.exists(aux_file):
                os.remove(aux_file)

        return self.standard_reply()

    async def do_execute(self, code, silent, store_history=False, user_expressions=None,
                         allow_stdin=False, *, cell_id=None):
        """
        Override of do_execute() method of IPythonKernel. If no custom magic commands specified,
        execute cell with super().do_execute(), else save Score-P environment/binding arguments/
        execute cell with Score-P Python binding.
        """
        if code.startswith('%%start_writefile'):
            # get file name from arguments of magic command
            writefile_cmd = code.split('\n')[0].split(' ')
            if len(writefile_cmd) > 1:
                if writefile_cmd[1].endswith('.py'):
                    self.writemode_filename = writefile_cmd[1][:-3]
                else:
                    self.writemode_filename = writefile_cmd[1]
            return self.start_writefile()
        elif code.startswith('%%end_writefile'):
            return self.end_writefile()
        elif self.writemode:
            return self.append_writefile(code)

        elif code.startswith('%%finalize_multicellmode'):
            if not self.multicellmode:
                self.cell_output(
                    "Error: Multicell mode disabled. Run a cell with %%enable_multicellmode command first.")
                return self.standard_reply()

            reply_status = await self.scorep_execute(self.multicell_code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
            self.multicell_code = ""
            self.multicellmode_cellcount = 0
            self.multicellmode = False
            return reply_status

        elif code.startswith('%%abort_multicellmode'):
            if not self.multicellmode:
                self.cell_output(
                    "Error: Multicell mode disabled. Run a cell with %%enable_multicellmode command first.")
                return self.standard_reply()
            return self.abort_multicellmode()
        elif code.startswith('%%enable_multicellmode'):
            return self.enable_multicellmode()

        elif code.startswith('%%scorep_env'):
            return self.set_scorep_env(code)
        elif code.startswith('%%scorep_python_binding_arguments'):
            return self.set_scorep_pythonargs(code)
        elif self.multicellmode:
            return self.append_multicellmode(code)
        elif code.startswith('%%execute_with_scorep'):
            return await self.scorep_execute(code.split("\n", 1)[1], silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)
        else:
            return await super().do_execute(code, silent, store_history, user_expressions, allow_stdin, cell_id=cell_id)


if __name__ == '__main__':
    from ipykernel.kernelapp import IPKernelApp
    IPKernelApp.launch_instance(kernel_class=ScorepPythonKernel)