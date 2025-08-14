from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple


MouseXY = Tuple[float, float]


@dataclass
class PrecisionMouseState:
    """
    Stateful helper to apply precision scaling to mouse movement only while a
    modifier (e.g., Shift) is held, without causing position jumps on toggle.

    Usage:
        state = PrecisionMouseState(scale=0.3)
        state.reset((mx, my))
        # per MOUSEMOVE
        adjusted = state.on_move((mx, my), shift=event.shift, current_adjusted_xy=current_xy)
    """

    active: bool = False
    anchor_screen: MouseXY | None = None
    anchor_adjusted: MouseXY | None = None
    scale: float = 0.3

    def reset(self, init_xy: MouseXY) -> None:
        """Initialize or reinitialize anchors and deactivate precision."""
        self.active = False
        self.anchor_screen = init_xy
        self.anchor_adjusted = init_xy

    def on_move(self, raw_xy: MouseXY, shift: bool, current_adjusted_xy: MouseXY) -> MouseXY:
        """
        Return adjusted mouse position for this frame.

        - When shift becomes active, anchors are captured to avoid jumps.
        - While active, output = anchor_adjusted + (raw - anchor_screen) * scale
        - When inactive, passthrough raw.
        """
        if not self.active and shift:
            # Enter precision: anchor at current positions
            self.active = True
            self.anchor_screen = raw_xy
            self.anchor_adjusted = current_adjusted_xy
        elif self.active and not shift:
            # Exit precision
            self.active = False

        if self.active and self.anchor_screen is not None and self.anchor_adjusted is not None:
            dx = raw_xy[0] - self.anchor_screen[0]
            dy = raw_xy[1] - self.anchor_screen[1]
            return (
                self.anchor_adjusted[0] + dx * self.scale,
                self.anchor_adjusted[1] + dy * self.scale,
            )
        else:
            return raw_xy
