// Inline handlers are blocked by the CSP, so the print button is wired here.
document.getElementById("printButton")?.addEventListener("click", () => window.print());
