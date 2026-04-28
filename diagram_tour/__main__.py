"""Allow `python -m diagram_tour [args]` to invoke the video renderer."""
from .render_video import main
import sys

if __name__ == "__main__":
    sys.exit(main())
