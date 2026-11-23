"""The Qt window. The only part of the desktop application that needs the `desktop` extra
(`PySide6-Essentials`); everything it shows comes from the framework-free modules next door.

Nothing here computes: the pages read `LocalSession`, `explorers`, `findings` and `health`, turn
what they return into widgets, and hand user input back. Charts are drawn by this package's own
QPainter code (`charts.py`) -- there is no charting dependency -- following the project's data
visualisation method: a validated categorical palette in a fixed order, thin marks, a legend for
two or more series, a tooltip that enhances but never gates, and a table view behind every chart.

One rule about signals, learned from a crash: connect a signal to a bound method of a Qt object
(`button.clicked.connect(self._go)`), and when a handler needs to know which widget it was for,
read it from `self.sender()` and a property or the action's data. Never connect a `lambda` (or a
`functools.partial`) that captures `self` or a widget. PySide keeps such a closure in the C++
connection, where Python's garbage collector cannot see it, so `widget -> button -> connection ->
closure -> widget` is a cycle that nothing frees until the interpreter exits, and then the two
sides each try to delete the other's objects. That showed up as heap corruption and an abort
(exit 134) at the end of the test run on CI. `test_desktop_ui_lifetime.py` checks both the rule
and the consequence.
"""
