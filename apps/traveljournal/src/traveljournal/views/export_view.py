from traveljournal.views.placeholder import PlaceholderView


class ExportView(PlaceholderView):
    def __init__(self) -> None:
        super().__init__(
            "Export",
            "Alle Exporter implementieren die gemeinsame Schnittstelle Exporter. "
            "Phase 8 liefert HTML mit Jinja2. PDF erfolgt über HTML oder LaTeX, "
            "nicht über PyMuPDF. CEWE bleibt ein lizenzrechtlich geprüfter Platzhalter.",
        )
