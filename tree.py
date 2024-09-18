from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Footer


class ANSIApp(App):
    CSS = """
    Screen {
        height: auto;
        max-height: 80vh;
        border: none;
       
    }
    DirectoryTree {
        height: auto;
        max-height: 100%;        
    }
    """
    INLINE_PADDING = 0

    def compose(self) -> ComposeResult:
        yield (
            tree := DirectoryTree(
                "/Users/willmcgugan/projects/textual/src/",
                classes="-ansi -ansi-scrollbar",
            )
        )
        tree.guide_depth = 3
        tree.show_root = False
        yield Footer(classes="-ansi-colors")

    def on_mount(self) -> None:
        tree = self.query_one(DirectoryTree)
        tree.select_node(tree.root)


if __name__ == "__main__":
    app = ANSIApp(ansi_color=True)
    app.run(inline=True)
