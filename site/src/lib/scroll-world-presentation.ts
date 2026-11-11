/** Decorates text only. The scroll engine retains its own nodes and transforms. */
export function decorateScrollHeading(heading: HTMLHeadingElement) {
  const text = heading.textContent ?? "";
  const stop = text.indexOf(". ");
  const lines = stop < 0 ? [text] : [text.slice(0, stop + 1), text.slice(stop + 2)];
  heading.setAttribute("aria-label", text);
  let order = 0;
  heading.replaceChildren(...lines.map((text, index) => {
    const line = document.createElement("span");
    line.className = "sw-title-line" + (index ? " sw-title-line--silver" : "");
    line.setAttribute("aria-hidden", "true");
    text.split(" ").forEach((word, wordIndex) => {
      if (wordIndex) line.append(" ");
      const mask = document.createElement("span");
      mask.className = "heading-word";
      const ink = document.createElement("span");
      ink.className = "heading-word__ink";
      ink.textContent = word;
      ink.dataset.ink = word;
      ink.style.setProperty("--word-order", String(Math.min(order++, 8)));
      mask.append(ink);
      line.append(mask);
    });
    // Preserve a natural space in selection and textContent between sentences.
    if (index < lines.length - 1) line.append(" ");
    return line;
  }));
}
