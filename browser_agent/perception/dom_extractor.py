from playwright.sync_api import Page


def _wait_for_page_stability(page: Page, timeout_ms: int = 6000):
    try:
        page.wait_for_selector(
            "button, a, input, textarea, select, [role='button'], h1, h2, h3, h4, h5, .card",
            state="attached",
            timeout=timeout_ms
        )
    except Exception:
        pass


def extract_headings(page: Page):
    try:
        return page.locator("h1, h2, h3, h4, h5, h6, .card-title, .title").evaluate_all("""
            elements => elements
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
                })
                .map(el => (el.innerText || el.textContent || "").trim())
                .filter(text => text.length > 0)
        """)
    except Exception:
        return []


def extract_buttons(page: Page):
    try:
        return page.locator(
            "button, [role='button'], input[type='button'], input[type='submit'], .btn, .button, div[onclick], span[onclick], div.card, div[class*='form-card']"
        ).evaluate_all("""
            elements => elements
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
                })
                .map(el => {
                    const text = (el.innerText || el.textContent || el.getAttribute("value") || el.getAttribute("aria-label") || "").trim();
                    const tagName = el.tagName.toLowerCase();
                    return {
                        text: text.replace(/\\s+/g, " "),
                        type: el.getAttribute("type") || (tagName === "button" ? "button" : "clickable"),
                        disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true")
                    };
                })
                .filter(btn => btn.text.length > 0 && btn.text.length < 150)
        """)
    except Exception:
        return []


def extract_links(page: Page):
    try:
        return page.locator("a").evaluate_all("""
            elements => elements
                .filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
                })
                .map(el => {
                    const text = (el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title") || "").trim();
                    return {
                        text: text.replace(/\\s+/g, " "),
                        href: el.href || "",
                        visible: true
                    };
                })
                .filter(link => link.text.length > 0)
        """)
    except Exception:
        return []


def extract_input_fields(page: Page):
    try:
        return page.locator(
            "input, textarea, select, [contenteditable='true']"
        ).evaluate_all("""
            elements => elements
                .filter(el => el.getAttribute("type") !== "hidden")
                .map((element, index) => {
                    let computedLabel = "";

                    if (element.labels && element.labels.length > 0) {
                        computedLabel = Array.from(element.labels)
                            .map(l => (l.innerText || l.textContent || "").trim())
                            .filter(Boolean)
                            .join(" ");
                    }

                    if (!computedLabel && element.getAttribute("aria-label")) {
                        computedLabel = element.getAttribute("aria-label").trim();
                    }

                    if (!computedLabel && element.getAttribute("aria-labelledby")) {
                        const labelId = element.getAttribute("aria-labelledby");
                        const labelEl = document.getElementById(labelId);
                        if (labelEl) {
                            computedLabel = (labelEl.innerText || labelEl.textContent || "").trim();
                        }
                    }

                    if (!computedLabel) {
                        const parent = element.closest("label, .form-group, .mat-form-field, .form-field, div");
                        if (parent) {
                            const clone = parent.cloneNode(true);
                            clone.querySelectorAll("input, textarea, select").forEach(n => n.remove());
                            const raw = (clone.innerText || clone.textContent || "").trim();
                            if (raw.length > 0 && raw.length < 80) {
                                computedLabel = raw;
                            }
                        }
                    }

                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    const isVisible = rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";

                    return {
                        field_ref: `field_${String(index + 1).padStart(4, "0")}`,
                        tag: element.tagName.toLowerCase(),
                        type: element.getAttribute("type") || (element.tagName.toLowerCase() === "textarea" ? "textarea" : "text"),
                        name: element.getAttribute("name") || "",
                        id: element.id || "",
                        label: computedLabel.replace(/\\s+/g, " "),
                        placeholder: element.getAttribute("placeholder") || "",
                        autocomplete: element.getAttribute("autocomplete") || "",
                        required: Boolean(element.required || element.getAttribute("aria-required") === "true"),
                        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
                        visible: isVisible
                    };
                })
        """)
    except Exception:
        return []


def extract_dom(page: Page):
    _wait_for_page_stability(page)

    return {
        "title": page.title(),
        "headings": extract_headings(page),
        "buttons": extract_buttons(page),
        "links": extract_links(page),
        "input_fields": extract_input_fields(page)
    }