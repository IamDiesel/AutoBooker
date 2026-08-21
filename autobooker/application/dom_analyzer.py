import structlog
from playwright.async_api import Page

from autobooker.domain.strategy import AvailableOption

logger = structlog.get_logger(__name__)


class DOMAnalyzerService:
    """
    Analysiert generisch HTML-Strukturen und extrahiert auswählbare Entitäten,
    damit der User im GUI interagieren kann, ohne den Code zu kennen.
    """

    async def extract_bookable_options(self, page: Page) -> list[AvailableOption]:
        """
        Scannt die Seite nach Checkboxen/Radios und verknüpft sie mit ihren Labels.
        """
        logger.info("dom_analyzer_scanning_page", url=page.url)

        # Wir injizieren ein Stück JavaScript in die Seite, das extrem robust und
        # generisch nach Formularelementen sucht.
        js_evaluation_script = """
        () => {
            const results = [];
            // Suche alle relevanten Inputs (kann beliebig um 'select' erweitert werden)
            const inputs = document.querySelectorAll('input[type="checkbox"], input[type="radio"]');
            
            for (const input of inputs) {
                // 1. Priorität: Das 'title' Attribut (in Deinem Shop für 'Anne Kahrizi' genutzt)
                let labelText = input.getAttribute('title') || "";
                
                // 2. Priorität: Verknüpftes <label for="...">
                if (!labelText && input.id) {
                    const label = document.querySelector(`label[for="${input.id}"]`);
                    if (label) {
                        // Nimm nur den sichtbaren Text, ignoriere versteckte Spans
                        labelText = label.innerText.trim().split('\\n')[0]; 
                    }
                }
                
                // 3. Priorität: Input liegt innerhalb eines <label>
                if (!labelText) {
                    const parentLabel = input.closest('label');
                    if (parentLabel) {
                        labelText = parentLabel.innerText.trim().split('\\n')[0];
                    }
                }
                
                if (labelText && input.name) {
                    results.push({
                        id: input.id || input.name,
                        label: labelText.trim(),
                        input_name: input.name,
                        input_value: input.value || "1",
                        element_type: input.type
                    });
                }
            }
            return results;
        }
        """

        # Führe JS im Browser aus
        raw_elements = await page.evaluate(js_evaluation_script)

        options: list[AvailableOption] = []
        for element in raw_elements:
            option = AvailableOption(**element)
            options.append(option)
            logger.debug("option_discovered", label=option.label, input_name=option.input_name)

        logger.info("dom_analyzer_finished", options_found=len(options))
        return options
