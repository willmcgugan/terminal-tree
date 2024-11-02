# /// script
# dependencies = [
#   "textual>=0.85.1",
#   "rich>=13.94",
# ]
# ///


import asyncio
import itertools
from dataclasses import dataclass
from datetime import datetime
import mimetypes
from pathlib import Path
import pwd
import grp
from stat import filemode
import threading

from rich import filesize
from rich.highlighter import Highlighter
from rich.syntax import Syntax

from rich.text import Text
from textual import on, events, work
from textual.reactive import reactive, var
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.cache import LRUCache
from textual.message import Message
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.validation import ValidationResult, Validator
from textual.widgets import DirectoryTree, Footer, Label, Tree, Input, Static
from textual.widgets.directory_tree import DirEntry


class DirectoryHighlighter(Highlighter):
    """Highlights directories in green, anything else in red."""

    def highlight(self, text: Text) -> None:
        path = Path(text.plain).expanduser().resolve()
        if path.is_dir():
            text.stylize("green")
        else:
            text.stylize("red")


class DirectoryValidator(Validator):
    """Validate a string is a valid directory path."""

    def validate(self, value: str) -> ValidationResult:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            return self.success()
        else:
            return self.failure("Directory required", value)


class ListDirCache:
    """A cache for listing a directory."""

    def __init__(self) -> None:
        self._cache: LRUCache[tuple[str, int], list[Path]] = LRUCache(100)
        self._lock = threading.Lock()

    async def listdir(self, path: Path, size: int) -> list[Path]:
        cache_key = (str(path), size)

        def iterdir_thread(path: Path) -> list[Path]:
            return list(itertools.islice(path.iterdir(), size))

        with self._lock:
            if cache_key in self._cache:
                paths = self._cache[cache_key]
            else:
                paths = await asyncio.to_thread(iterdir_thread, path)
                self._cache[cache_key] = paths
            return paths


class DirectorySuggester(Suggester):
    """Suggest a directory."""

    def __init__(self) -> None:
        self._cache = ListDirCache()
        super().__init__()

    async def get_suggestion(self, value: str) -> str | None:
        """Suggest the first matching directory."""

        try:
            path = Path(value)
            name = path.name

            children = await self._cache.listdir(
                path.expanduser() if path.is_dir() else path.parent.expanduser(), 100
            )
            possible_paths = [
                f"{sibling_path}/"
                for sibling_path in children
                if sibling_path.name.lower().startswith(name.lower())
                and sibling_path.is_dir()
            ]
            if possible_paths:
                possible_paths.sort(key=str.__len__)
                suggestion = possible_paths[0]

                if "~" in value:
                    home = str(Path("~").expanduser())
                    suggestion = suggestion.replace(home, "~", 1)
                return suggestion

        except FileNotFoundError:
            pass
        return None


class PathComponent(Label):
    """Clickable component in a path."""

    DEFAULT_CSS = """
    PathComponent {
      &:hover { text-style: reverse; }  
    }
    """

    def on_click(self, event: events.Click) -> None:
        self.post_message(PathNavigator.NewPath(Path(self.name or "")))


class InfoBar(Horizontal):
    DEFAULT_CSS = """
    InfoBar {
        margin: 0 1;
        height: 1;
        dock: bottom;
        .error { color: ansi_bright_red; }
        .mode { color: ansi_red; }
        .user-name { color: ansi_green; }
        .group-name { color: ansi_yellow; }
        .file-size {
            color: ansi_magenta;
            text-style: bold;
        }
        .modified-time { color: ansi_cyan; }
        Label { margin: 0 1 0 0; }        
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
        try:
            stat = self.path.stat()
        except Exception:
            yield Label("failed to get file info", classes="error")
        else:
            user_name = pwd.getpwuid(stat.st_uid).pw_name
            group_name = grp.getgrgid(stat.st_gid).gr_name
            modified_time = datetime.fromtimestamp(stat.st_mtime)

            yield Label(filemode(stat.st_mode), classes="mode")
            yield Label(user_name, classes="user-name")
            yield Label(group_name, classes="group-name")
            yield Label(
                self.datetime_to_ls_format(modified_time), classes="modified-time"
            )
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
        .separator { margin: 0 0; }      
    }
    """

    path: reactive[Path] = reactive(Path, recompose=True)
    edit = reactive(False, recompose=True)

    def compose(self) -> ComposeResult:
        path = self.path.resolve().absolute()

        yield Label("📁 ", classes="separator")
        components = str(path).split("/")
        root_component = PathComponent("/", name="/")
        root_component.tooltip = "/"
        yield root_component
        for index, component in enumerate(components, 1):
            partial_path = "/".join(components[:index])
            component_label = PathComponent(component, name=partial_path)
            component_label.tooltip = partial_path
            yield component_label
            if index > 1 and index < len(components):
                yield Label("/", classes="separator")


class PathScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss", "cancel")]

    CSS = """
    PathScreen {
        align: center top;        
        Horizontal {
            margin-left: 1;               
            height: 1;
            dock: top;
        }
        Input {                    
            padding: 0 1;
            border: none !important;
            height: 1;           
            &>.input--placeholder, &>.input--suggestion {
                text-style: dim not bold !important;
                color: ansi_default;
            }    
            &.-valid {
                text-style: bold;
                color: ansi_green;
            }
            &.-invalid {
                text-style: bold;
                color: ansi_red;
            }
        }       
    }
    """

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path.rstrip("/") + "/"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("📂")
            yield Input(
                value=self.path,
                validators=[DirectoryValidator()],
                suggester=DirectorySuggester(),
                classes="-ansi-colors",
            )
        yield (footer := Footer(classes="-ansi-colors"))
        footer.compact = True

    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.input.value)

    def action_dismiss(self):
        self.dismiss(None)


class PreviewWindow(ScrollableContainer):
    """Widget to show a preview of a file."""

    ALLOW_MAXIMIZE = True
    DEFAULT_CSS = """
    PreviewWindow {
        width: 1fr;
        height: 1fr;
        border: heavy blank;
        overflow-y: scroll;
        &:focus { border: heavy ansi_blue; }
        #content { width: auto; }
        &.-preview-unavailable {
            overflow: auto;
            hatch: right ansi_black;
            align: center middle;
            text-style: bold;
            color: ansi_red;
        }   
    }
    """
    DEFAULT_CLASSES = "-ansi-scrollbar"

    path: var[Path] = var(Path)

    @work(exclusive=True)
    async def get_syntax(self, path: Path) -> None:
        content = self.query_one("#content", Static)
        if path.is_file():
            file_type, encoding = mimetypes.guess_type(str(path))
            if file_type and file_type.startswith("text/"):
                # A text file, we can attempt to syntax highlight it
                with open(path, "rt", encoding=encoding) as text_file:
                    lines = text_file.readlines(1024 * 64)
                code = "".join(lines)

                lexer = Syntax.guess_lexer(str(path), code)
                try:
                    syntax = Syntax(
                        code,
                        lexer,
                        word_wrap=False,
                        indent_guides=True,
                        line_numbers=True,
                        theme="ansi_light",
                    )
                except Exception:
                    return
                self.call_later(content.update, syntax)
                self.remove_class("-preview-unavailable")
            else:
                # Try to display it is plain text
                with open(path, "rb") as binary_file:
                    data = binary_file.read(1024 * 64)
                try:
                    text = data.decode(encoding or "utf-8")
                except Exception:
                    # Can't be decoded as text
                    self.call_later(content.update, "Preview not available")
                    self.add_class("-preview-unavailable")
                else:
                    syntax = Syntax(
                        text,
                        lexer="text",
                        word_wrap=False,
                        indent_guides=True,
                        line_numbers=True,
                        theme="ansi_light",
                    )
                    self.call_later(content.update, syntax)
                    self.remove_class("-preview-unavailable")

    def watch_path(self, path: Path) -> None:
        self.get_syntax(path)

    def compose(self) -> ComposeResult:
        yield Static("", id="content")


class PathNavigator(Horizontal):
    DEFAULT_CSS = """
    PathNavigator {
        height: auto;
        max-height: 100%;
        DirectoryTree {            
            height: auto;    
            max-height: 100%;
            width: 1fr;
            border: heavy blank;
            &:focus { border: heavy ansi_blue; }   
        }
        PreviewWindow { display: None; }    
        &.-show-preview {        
            PreviewWindow { display: block; }
        }
    }

    """

    BINDINGS = [
        Binding("r", "reload", "reload", tooltip="Refresh tree from filesystem"),
        Binding("g", "goto", "go to", tooltip="Go to a new root path"),
        Binding("p", "toggle_preview", "preview", tooltip="Toggle the preview pane"),
    ]

    path: reactive[Path] = reactive(Path)
    show_preview: reactive[bool] = reactive(False)

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

    def watch_show_preview(self, show_preview: bool) -> None:
        self.set_class(show_preview, "-show-preview")

    @on(Tree.NodeHighlighted)
    def on_node_highlighted(self, event: Tree.NodeHighlighted[DirEntry]) -> None:
        if event.node.data is not None:
            self.query_one(InfoBar).path = event.node.data.path
            self.query_one(PreviewWindow).path = event.node.data.path

    @on(NewPath)
    def on_new_path(self, event: NewPath) -> None:
        event.stop()
        if not event.path.is_dir():
            self.notify(
                f"'{self.path}' is not a directory",
                title="Change Directory",
                severity="error",
            )
        else:
            self.path = event.path
            self.query_one(DirectoryTree).path = event.path
            self.query_one(PathDisplay).path = event.path

    def compose(self) -> ComposeResult:
        yield PathDisplay()
        tree = DirectoryTree(self.path, classes="-ansi -ansi-scrollbar")
        tree.guide_depth = 3
        tree.show_root = False
        tree.center_scroll = True
        yield tree
        yield PreviewWindow()
        yield InfoBar()

    async def action_reload(self) -> None:
        tree = self.query_one(DirectoryTree)
        if tree.cursor_node is None:
            await tree.reload()
            self.notify("👍 Reloaded directory contents", title="Directory")
        else:
            reload_node = tree.cursor_node.parent
            assert reload_node is not None and reload_node.data is not None
            path = reload_node.data.path
            await tree.reload_node(reload_node)
            self.notify(f"👍 Reloaded {str(path)!r}", title="Reload")

    @work
    async def action_goto(self) -> None:
        new_path = await self.app.push_screen_wait(PathScreen(str(self.path)))
        if new_path is not None:
            self.post_message(PathNavigator.NewPath(Path(new_path)))

    async def action_toggle_preview(self) -> None:
        self.show_preview = not self.show_preview
        self.screen.minimize()


class NavigatorApp(App):
    CSS = """
    Screen {
        height: auto;
        max-height: 80vh;
        border: none;
        Footer { margin: 0 1 !important; }
        &.-maximized-view {
            height: 100vh;  
            hatch: right ansi_black;          
        }
        .-maximized { margin: 1 2; }
    }
    """
    ALLOW_IN_MAXIMIZED_VIEW = ""
    INLINE_PADDING = 0

    def compose(self) -> ComposeResult:
        yield PathNavigator(Path("~/"))
        footer = Footer(classes="-ansi-colors")
        footer.compact = True
        yield footer

    def on_mount(self) -> None:
        tree = self.query_one(DirectoryTree)
        tree.cursor_line = 0


def run():
    app = NavigatorApp(ansi_color=True)
    app.run(inline=True)


if __name__ == "__main__":
    run()
