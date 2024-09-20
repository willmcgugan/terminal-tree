from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import pwd
import grp
from stat import filemode

from rich import filesize

from textual import on, events
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.message import Message
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree, Footer, Label, Tree
from textual.widgets.directory_tree import DirEntry


def datetime_to_ls_format(dt):
    # Check if the datetime is from the current year
    if dt.year == datetime.now().year:
        # If it's the current year, use a format without the year
        return dt.strftime("%d %b %H:%M")
    else:
        # If it's not the current year, include the year instead of time
        return dt.strftime("%d %b  %Y")


class PathComponent(Label):
    DEFAULT_CSS = """
    PathComponent {
      &:hover {
        text-style: reverse;
      }  
    }
    """

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(PathNavigator.NewPath(Path(self.name or "")))


class InfoBar(Horizontal):
    DEFAULT_CSS = """
    InfoBar {
        height: 1;
        dock: bottom;
        .mode {
            color: ansi_red;
        }
        .user-name {
            color: ansi_green;
        }
        .group-name {
            color: ansi_yellow;
        }
        .file-size {
            color: ansi_magenta;
            text-style:
        }
        .modified-time {
            color: ansi_cyan;
        }

        Label {
            margin: 0 1 0 0;
        }
    }
    """

    path: reactive[Path] = reactive(Path, recompose=True)

    def compose(self) -> ComposeResult:
        stat = self.path.stat()
        yield Label(filemode(stat.st_mode), classes="mode")

        user_name = pwd.getpwuid(stat.st_uid).pw_name
        yield Label(user_name, classes="user-name")

        group_name = grp.getgrgid(stat.st_gid).gr_name
        yield Label(group_name, classes="group-name")

        modified_time = datetime.fromtimestamp(stat.st_mtime)
        yield Label(datetime_to_ls_format(modified_time), classes="modified-time")

        if not self.path.is_dir():
            label = Label(filesize.decimal(stat.st_size), classes="file-size")
            label.tooltip = f"{stat.st_size} bytes"
            yield label


class PathDisplay(Horizontal):
    DEFAULT_CSS = """
    PathDisplay {
        layout: horizontal;
        height: 1;
        dock: top;
        align: center top;
        text-style:  bold ;
        color: ansi_green;

        .separator {
            margin: 0 0;
            
        }
    }

    """

    path: reactive[Path] = reactive(Path, recompose=True)

    def compose(self) -> ComposeResult:
        path = self.path.resolve().absolute()
        yield Label("📁 ", classes="separator")

        components = str(path).split("/")
        for index, component in enumerate(components, 1):
            partial_path = "/".join(components[:index])
            component_label = PathComponent(component, name=partial_path)
            component_label.tooltip = partial_path
            yield component_label
            if index < len(components):
                yield Label("/", classes="separator")


class PathNavigator(Vertical):
    DEFAULT_CSS = """
    PathNavigator {
        height: auto;
        max-height: 100%;
        DirectoryTree {            
            height: auto;    
            max-height: 100%;        
        }
    }

    """

    path: reactive[Path] = reactive(Path)

    @dataclass
    class NewPath(Message):
        path: Path

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def validate_path(self, path: Path) -> Path:
        return path.expanduser().resolve()

    def on_mount(self) -> None:
        self.post_message(PathNavigator.NewPath(self.path))

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted[DirEntry]) -> None:
        if event.node.data is not None:
            self.query_one(InfoBar).path = event.node.data.path

    @on(NewPath)
    def on_new_path(self, event: NewPath) -> None:
        event.stop()
        self.query_one(DirectoryTree).path = event.path
        self.query_one(PathDisplay).path = event.path

    def compose(self) -> ComposeResult:
        yield PathDisplay()
        tree = DirectoryTree(self.path, classes="-ansi -ansi-scrollbar")
        tree.guide_depth = 3
        tree.show_root = False
        tree.center_scroll = True
        yield tree
        yield InfoBar()


class ANSIApp(App):
    CSS = """
    Screen {
        height: auto;
        max-height: 80vh;
        border: none;
    }
   
    """
    INLINE_PADDING = 0

    def compose(self) -> ComposeResult:
        yield PathNavigator(Path("~/projects/textual"))

        yield Footer(classes="-ansi-colors")

    def on_mount(self) -> None:
        tree = self.query_one(DirectoryTree)
        tree.select_node(tree.root)


if __name__ == "__main__":
    app = ANSIApp(ansi_color=True)
    app.run(inline=True)
