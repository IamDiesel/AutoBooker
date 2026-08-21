from typing import Any, Literal

from pydantic import BaseModel, Field


class AvailableOption(BaseModel):
    """
    Repräsentiert ein im DOM gefundenes, auswählbares Element.
    Wird an das GUI gereicht, um dynamische Schalter zu erzeugen.
    """

    id: str
    label: str  # z. B. "Max Mustermann"
    input_name: str  # z. B. "selected_customer_list[1234567]"
    input_value: str  # z. B. "1"
    element_type: Literal["checkbox", "radio", "select", "hidden", "unknown"]


class FormAction(BaseModel):
    """
    Eine atomare Aktion (Command Pattern), die ausgeführt wird,
    um ein Element in den Warenkorb zu legen.
    """

    name: str
    value: Any


class BookingStrategy(BaseModel):
    """
    Die kompilierte Strategie. Enthält alle Actions, die der Orchestrator
    beim Live-Drop in ein URL-kodiertes Formular oder JSON umwandelt.
    """

    target_url: str = ""
    actions: list[FormAction] = Field(default_factory=list)

    def generate_form_payload(self) -> str:
        """Kompiliert die Actions zu einem x-www-form-urlencoded String."""
        import urllib.parse

        # Wir nutzen quote_plus, damit Leerzeichen korrekt als '+' oder '%20' kodiert werden
        payload_parts = [
            f"{urllib.parse.quote_plus(action.name)}={urllib.parse.quote_plus(str(action.value))}"
            for action in self.actions
        ]
        return "&".join(payload_parts)
