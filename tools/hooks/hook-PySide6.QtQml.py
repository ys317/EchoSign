"""Ship only the QML modules used by the Basic-style desktop.

The stock hook collects every installed PySide addon, including unrelated GPL
modules. Limit imports before binary dependency analysis, retaining dynamic DLLs.
"""
from pathlib import PurePath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
qml_root = PurePath(pyside6_library_info.qt_rel_dir) / 'qml'


def needed(entry):
    target = PurePath(entry[1]).relative_to(qml_root).as_posix()
    return (target == 'QtQml' or target.startswith('QtQml/')
            or target in ('QtQuick', 'QtQuick/Window', 'QtQuick/Layouts',
                          'QtQuick/Templates', 'QtQuick/Controls', 'QtQuick/Controls/impl')
            or target.startswith('QtQuick/Controls/Basic'))


binaries += [entry for entry in qml_binaries if needed(entry)]
datas += [entry for entry in qml_datas if needed(entry)]
