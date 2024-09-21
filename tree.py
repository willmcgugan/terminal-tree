from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import pwd
import grp
from stat import filemode

from rich import filesize
from rich.highlighter import Highlighter

from rich.text import Text
from textual import on, events
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.validation import ValidationResult, Validator
from textual.widgets import DirectoryTree, Footer, Label, Tree, Input
from textual.widgets.directory_tree import DirEntry


class DirectoryHighlighter(Highlighter):
    """Highlights directories in green, anything else in red."""

    def highlight(self, text: Text) -> Text:
        path = Path(text.plain).expanduser().resolve()
        if path.is_dir():
            text.stylize("green")
        else:
            text.stylize("red")
        return text


class DirectoryValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            return self.success()
        else:
            return self.failure("Directory required", value)


class PathComponent(Label):
    DEFAULT_CSS = """
    PathComponent {
      &:hover {
        text-style: reverse;
      }  
    }
    """

    def on_click(self, event: events.Click) -> None:
        self.post_message(PathNavigator.NewPath(Path(self.name or "")))


class InfoBar(Horizontal):
    DEFAULT_CSS = """
    InfoBar {
        height: 1;
        dock: bottom;
        .mode { color: ansi_red; }
        .user-name { color: ansi_green; }
        .group-name { color: ansi_yellow; }
        .file-size {
            color: ansi_magenta;
            text-style: bold;
        }
        .modified-time { color: ansi_cyan; }
        Label {
            margin: 0 1 0 0;
        }
    }
    """

    path: reactive[Path] = reactive(Path, recompose=True)

    @staticmethod
    def datetime_to_ls_format(date_time: datetime) -> str:
        """Convert a datetime object to a string format similar to ls -la output."""
        if date_time.year == datetime.now().year:
            # For dates in the current year, use format: "day month HH:MM"
            return date_time.strftime("%d %b %H:%M")
        else:
            # For dates not in the current year, use format: "day month  year"
            return date_time.strftime("%d %b %Y")

    def compose(self) -> ComposeResult:
        stat = self.path.stat()
        user_name = pwd.getpwuid(stat.st_uid).pw_name
        group_name = grp.getgrgid(stat.st_gid).gr_name
        modified_time = datetime.fromtimestamp(stat.st_mtime)

        yield Label(filemode(stat.st_mode), classes="mode")
        yield Label(user_name, classes="user-name")
        yield Label(group_name, classes="group-name")
        yield Label(self.datetime_to_ls_format(modified_time), classes="modified-time")
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
        text-style: bold;
        color: ansi_green;

        .separator {
            margin: 0 0;   
        }

        

    }
    """

    path: reactive[Path] = reactive(Path, recompose=True)
    edit = reactive(False, recompose=True)

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


class PathScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Cancel go to directory")]

    DEFAULT_CSS = """
    PathScreen {
        align: center middle;
        Input {
            width: 80%;
           
        }

    }
    """

    path: reactive[str] = reactive("", recompose=True)

    def compose(self) -> ComposeResult:
        yield Input(
            value=self.path,
            validators=[DirectoryValidator()],
            classes="-ansi-colors",
        )

    def action_dismiss(self):
        self.dismiss()


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

    BINDINGS = [
        Binding("r", "reload", "Reload"),
        Binding("g", "goto", "Go to directory"),
    ]

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

    async def action_reload(self) -> None:
        tree = self.query_one(DirectoryTree)
        if tree.cursor_node is None:
            await tree.reload()
            self.notify("👍 Reloaded directory contents", title="Directory")
        else:
            reload_node = tree.cursor_node.parent
            path = reload_node.data.path
            await tree.reload_node(reload_node)
            self.notify(f"👍 Reloaded {str(path)!r}", title="Reload")

    def action_goto(self) -> None:
        self.app.push_screen(PathScreen())


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
        footer = Footer(classes="-ansi-colors")
        footer.compact = True
        yield footer

    def on_mount(self) -> None:
        tree = self.query_one(DirectoryTree)
        tree.select_node(tree.root)


if __name__ == "__main__":
    app = ANSIApp(ansi_color=True)
    app.run(inline=True)
