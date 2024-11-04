
An experimental filesystem navigator for the terminal, built with [Textual](https://github.com/textualize/textual)


https://github.com/user-attachments/assets/de4c9bab-4cfa-4295-bd2e-450df855ef0d

This could form the basis of a file manager / picker.
For now, consider it a UI experiment.

PS Its a [single file](https://github.com/willmcgugan/terminal-tree/blob/main/tree.py).

## Installing

This project isn't on Pypi or other package manager, but thanks to the sorcery that is [uv](https://docs.astral.sh/uv/guides/tools/) you can try it out with the following command:

```
uvx --from git+https://github.com/willmcgugan/terminal-tree.git --python 3.12 -q terminal-tree
```

Tested in macOS only at this point. Chances are very high it works on Linux. Slightly lower chance (but non-zero) that it works on Windows.

## Tree navigation

![tree_navigator](https://github.com/user-attachments/assets/52705568-4d1b-47e5-9d5b-d7bfe8ad509e)

A directory tree that may be navigated by the keyboard or mouse.

## File preview

![file_preview](https://github.com/user-attachments/assets/79d2d351-abca-45f6-82b2-5c7a82fef316)

Some text file-types may be displayed with syntax highlighting in a preview panel.

This preview panel may be maximized from the command palette.

## Path completion and validation

![path_complete](https://github.com/user-attachments/assets/6ae4a414-9b4d-4b5d-812a-fdb8ddf3381c)

Hit `g` to edit the current path.

The path will auto-complete as you type. Press `right` to accept the auto-completion.

The path is also validated as you type. Invalid (non directory) paths are highlighted in red, or green if it is a valid path.

## Path components

![path_select](https://github.com/user-attachments/assets/6310badf-a5ba-43fc-a8fd-97cce69ad161)


You can also click on a path component to navigate to a parent directory.

## No issues please

I don't know is this will become a standalone tool, or be folded back in to [Textual](https://github.com/textualize/textual).

If you are interested in this project, please fork it. let me know if you do anything interesting with it!
