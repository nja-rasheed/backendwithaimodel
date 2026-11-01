from playwright.sync_api import Page


def extract_headings(page: Page):
    return page.locator("h1, h2, h3").all_text_contents()


def extract_buttons(page: Page):
    return page.locator("button").evaluate_all("""
        elements => elements.map(element => ({
            text: element.innerText.trim(),
            type: element.getAttribute("type"),
            disabled: element.disabled
        }))
    """)


def extract_links(page: Page):
    return page.locator("a").evaluate_all("""
        elements => elements
            .filter(element => element.innerText.trim())
            .map(element => ({
                text: element.innerText.trim(),
                href: element.href,
                visible: element.getClientRects().length > 0
            }))
    """)


def extract_input_fields(page: Page):
    return page.locator(
        "input, textarea, select"
    ).evaluate_all("""
        elements => elements.map((element, index) => ({
            field_ref: `field_${String(index + 1).padStart(4, "0")}`,

            tag: element.tagName.toLowerCase(),

            type: element.getAttribute("type") || "text",

            name: element.getAttribute("name"),

            id: element.id,

            label: (
                Array.from(element.labels || [])
                    .map(label => label.innerText.trim())
                    .filter(Boolean)
                    .join(" ")
                || element.getAttribute("aria-label")
                || ""
            ),

            placeholder: element.getAttribute("placeholder"),

            autocomplete: element.getAttribute("autocomplete"),

            required: element.required,

            disabled: element.disabled
        }))
    """)

def extract_dom(page: Page):

    return {
        "title": page.title(),
        "headings": extract_headings(page),
        "buttons": extract_buttons(page),
        "links": extract_links(page),
        "input_fields": extract_input_fields(page)
    }