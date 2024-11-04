# /// script
# dependencies = [
#   "textual>=0.85.2",
#   "rich>=13.9.4",
# ]
# ///


import asyncio
import grp
import itertools
import mimetypes
import pwd
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from stat import filemode

from rich import filesize
from rich.highlighter import Highlighter
from rich.syntax import Syntax
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.cache import LRUCache
from textual.containers import Horizontal, ScrollableContainer
from textual.message import Message
from textual.reactive import reactive, var
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.validation import ValidationResult, Validator
from textual.widgets import DirectoryTree, Footer, Input, Label, Static, Tree
from textual.widgets.directory_tree import DirEntry
from textual.worker import get_current_worker


class DirectoryHighlighter(Highlighter):
    """Highlights directories in green, anything else in red.

    This is a [Rich highlighter](https://rich.readthedocs.io/en/latest/highlighting.html),
    which can stylize Text based on dynamic criteria.

    Here we are highlighting valid directory paths in green, and invalid directory paths in red.

    """

    def highlight(self, text: Text) -> None:
        path = Path(text.plain).expanduser().resolve()
        if path.is_dir():
            text.stylize("green")
        else:
            text.stylize("red")


class DirectoryValidator(Validator):
    """Validate a string is a valid directory path.

    This is a Textual [Validator](https://textual.textualize.io/widgets/input/#validating-input) used by
    the input widget.

    """

    def validate(self, value: str) -> ValidationResult:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            return self.success()
        else:
            return self.failure("Directory required", value)


class ListDirCache:
    """A cache for listing a directory (not a Rich / Textual object).

    This class is responsible for listing directories, and caching the results.

    Listing a directory is a blocking operation, which is why we defer the work to a thread.

    """

    def __init__(self) -> None:
        self._cache: LRUCache[tuple[str, int], list[Path]] = LRUCache(100)
        self._lock = threading.Lock()

    async def listdir(self, path: Path, size: int) -> list[Path]:
        cache_key = (str(path), size)

        def iterdir_thread(path: Path) -> list[Path]:
            """Run iterdir in a thread.

            Returns:
                A list of paths.
            """
            return list(itertools.islice(path.iterdir(), size))

        with self._lock:
            if cache_key in self._cache:
                paths = self._cache[cache_key]
            else:
                paths = await asyncio.to_thread(iterdir_thread, path)
                self._cache[cache_key] = paths
            return paths


class DirectorySuggester(Suggester):
    """Suggest a directory.

    This is a [Suggester](https://textual.textualize.io/api/suggester/#textual.suggester.Suggester) instance,
    used by the Input widget to suggest auto-completions.

    """

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
    """Clickable component in a path.

    A simple widget that displays text with a hover effect, that sends
    a message when clicked.

    """

    DEFAULT_CSS = """
    PathComponent {
      &:hover { text-style: reverse; }  
    }
    """

    def on_click(self, event: events.Click) -> None:
        self.post_message(PathNavigator.NewPath(Path(self.name or "")))


class InfoBar(Horizontal):
    """A widget to display information regarding a file, such as user / size / modification date."""

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
    """A widget to display the path at the top of the UI.

    Not just simple text, this consists of clickable path components.

    """

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
    """A [Modal screen](https://textual.textualize.io/guide/screens/#modal-screens) containing an editable path.

    This is displayed when the user summons the "goto" functionality.

    As a modal screen, it is displayed on top of the previous screen, but only the widgets
    her will be usable.

    """

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
            # The validator and suggester instances pack a lot of functionality in to this input.
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
        """If the user submits the input (with enter), we return the value of the input to the caller."""
        self.dismiss(event.input.value)

    def action_dismiss(self):
        """If the user dismisses the screen with the escape key, we return None to the caller."""
        self.dismiss(None)


class PreviewWindow(ScrollableContainer):
    """Widget to show a preview of a file.

    A scrollable container that contains a [Rich Syntax](https://rich.readthedocs.io/en/latest/syntax.html) object
    which highlights and formats text.

    """

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
    async def update_syntax(self, path: Path) -> None:
        """Update the preview in a worker.

        A worker runs the code in a concurrent asyncio Task.

        Args:
            path: A Path to the file to get the content for.
        """
        worker = get_current_worker()
        content = self.query_one("#content", Static)
        if path.is_file():
            _file_type, encoding = mimetypes.guess_type(str(path))

            # A text file, we can attempt to syntax highlight it
            def read_lines() -> list[str] | None:
                """A function to read lines from path in a thread."""
                try:
                    with open(path, "rt", encoding=encoding or "utf-8") as text_file:
                        return text_file.readlines(1024 * 32)
                except Exception:
                    # We could be more precise with error handling here, but for now
                    # we will treat all errors as fails.
                    return None

            # Read the lines in a thread so as not to pause the UI
            lines = await asyncio.to_thread(read_lines)
            if lines is None:
                self.call_later(content.update, "Preview not available")
                self.add_class("-preview-unavailable")
                return

            if worker.is_cancelled:
                return

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
            content.update(syntax)
            self.remove_class("-preview-unavailable")

    def watch_path(self, path: Path) -> None:
        self.update_syntax(path)

    def compose(self) -> ComposeResult:
        yield Static("", id="content")


class PathNavigator(Horizontal):
    """The top-level widget, containing the directory tree and preview window."""

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
        Binding("q", "quit", "exit", tooltip="exit from terminal-tree"),
    ]

    path: reactive[Path] = reactive(Path)
    show_preview: reactive[bool] = reactive(False)

    @dataclass
    class NewPath(Message):
        """Message sent when the path is updated."""

        path: Path

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def validate_path(self, path: Path) -> Path:
        """Called to validate the path reactive."""
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
        """Action to goto a new path.

        This is a worker, because we want to wait on another screen without pausing the event loop.

        Without the "@work" decorator, the UI would be frozen.

        """
        new_path = await self.app.push_screen_wait(PathScreen(str(self.path)))
        if new_path is not None:
            self.post_message(PathNavigator.NewPath(Path(new_path)))

    async def action_toggle_preview(self) -> None:
        self.show_preview = not self.show_preview
        self.screen.minimize()

    async def action_quit(self) -> None:
        exit()


class NavigatorApp(App):
    """The App class.

    Most app's (like this one) don't contain a great deal of functionality.
    They exist to provide CSS, and to create the initial UI.

    """

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
        """Highlight the first line of the directory tree on startup."""
        self.query_one(DirectoryTree).cursor_line = 0


def run():
    """A function to run the app."""
    # We want ANSI color rather than truecolor.
    app = NavigatorApp(ansi_color=True)
    # Running inline will display the app below the prompt, rather than go fullscreen.
    app.run(inline=True)


if __name__ == "__main__":
    run()
