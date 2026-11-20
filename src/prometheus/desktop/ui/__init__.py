"""The Qt window. The only part of the desktop application that needs the `desktop` extra
(`PySide6-Essentials`); everything it shows comes from the framework-free modules next door.

Nothing here computes: the pages read `LocalSession`, `explorers`, `findings` and `health`, turn
what they return into widgets, and hand user input back. Charts are drawn by this package's own
QPainter code (`charts.py`) -- there is no charting dependency -- following the project's data
visualisation method: a validated categorical palette in a fixed order, thin marks, a legend for
two or more series, a tooltip that enhances but never gates, and a table view behind every chart.
"""
