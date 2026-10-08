@echo off
rem Run the editor; installs PySide6 on first launch
python -c "import PySide6" 2>nul || python -m pip install -r "%~dp0requirements.txt"
start "" pythonw "%~dp0redactor_md.py" %*
