from __future__ import annotations

import os
import subprocess
from typing import Any


def install_hidden_multiprocessing_spawn() -> bool:
    if os.name != "nt":
        return False
    import multiprocessing.popen_spawn_win32 as popen_spawn_win32

    if bool(getattr(popen_spawn_win32, "_zz_hidden_spawn_installed", False)):
        return True
    original_create_process = popen_spawn_win32._winapi.CreateProcess
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

    def create_process_no_window(
        application_name: Any,
        command_line: Any,
        process_attributes: Any,
        thread_attributes: Any,
        inherit_handles: Any,
        creation_flags: Any,
        environment: Any,
        current_directory: Any,
        startup_info: Any,
    ) -> Any:
        return original_create_process(
            application_name,
            command_line,
            process_attributes,
            thread_attributes,
            inherit_handles,
            int(creation_flags) | create_no_window,
            environment,
            current_directory,
            startup_info,
        )

    popen_spawn_win32._zz_hidden_spawn_original_create_process = original_create_process
    popen_spawn_win32._winapi.CreateProcess = create_process_no_window
    popen_spawn_win32._zz_hidden_spawn_installed = True
    return True
