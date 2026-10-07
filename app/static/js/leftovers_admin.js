(() => {
    const {el, readBootstrap, createAlert, createRequester, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("leftoversAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const UNIT_LABELS = {g: "g", kg: "kg", ml: "ml", l: "l", unit: "ud."};
    const MAX_SELECTION = 8;

    const state = {
        restaurantId: bootstrap.restaurantId,
        aiAvailable: bootstrap.ai_available,
        items: bootstrap.items || [],
        selected: new Set(),
        loadingIdeas: false,
    };

    const $ = (id) => document.getElementById(id);
    const showAlert = createAlert($("menuAdminAlert"));
    const request = createRequester("/api/inventory");
    const money = new Intl.NumberFormat("es-ES", {style: "currency", currency: bootstrap.currency || "EUR"});
    const number = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3});
    const quantity = (value, unit) => `${number.format(value)} ${UNIT_LABELS[unit] || unit}`;

    function reasonChip(reason, item) {
        switch (reason.code) {
        case "waste":
            return el("span", {className: "stock-badge is-critical", text: `Tirado ${quantity(reason.amount, item.unit)} en 30 días`});
        case "overstock":
            return el("span", {className: "stock-badge is-warning", text: `${quantity(reason.amount, item.unit)} por encima del ideal`});
        case "slow":
            return el("span", {className: "stock-badge is-warning", text: `Para ${number.format(Math.round(reason.days_of_cover))} días al ritmo actual`});
        default:
            return el("span", {className: "dish-hidden-badge", text: "No está en ninguna receta"});
        }
    }

    function leftoverCard(item) {
        const activeDishes = item.dishes.filter((dish) => dish.is_active);
        const hiddenDishes = item.dishes.filter((dish) => !dish.is_active);
        const checkbox = el("input", {attrs: {type: "checkbox", "data-select": item.inventory_item_id, "aria-label": `Usar ${item.name} para pedir ideas`, disabled: !state.aiAvailable}});
        checkbox.checked = state.selected.has(item.inventory_item_id);

        let suggestion;
        if (activeDishes.length) {
            const servings = (count) => (count >= 100 ? "más de 100 raciones" : `hasta ${plural(count, "ración", "raciones")}`);
            suggestion = `Empuja ${activeDishes.map((dish) => dish.servings_possible !== null ? `${dish.name} (${servings(dish.servings_possible)})` : dish.name).join(", ")} como sugerencia del día.`;
        } else if (hiddenDishes.length) {
            suggestion = `Lo usan platos ocultos de tu carta: ${hiddenDishes.map((dish) => dish.name).join(", ")}. Puedes recuperarlos en «Carta».`;
        } else {
            suggestion = "Ningún plato de tu carta lo usa: es buen candidato para una idea nueva.";
        }

        return el("article", {className: `dish-card leftover-card${state.selected.has(item.inventory_item_id) ? " is-selected" : ""}`}, [
            el("label", {className: "purchase-check"}, [checkbox]),
            el("div", {className: "dish-card-main"}, [
                el("div", {className: "dish-badges"}, item.reasons.map((reason) => reasonChip(reason, item))),
                el("h3", {text: item.name}),
                el("p", {className: "dish-description", text: `Tienes ${quantity(item.current_stock, item.unit)}${item.ideal_stock ? ` (ideal ${quantity(item.ideal_stock, item.unit)})` : ""}${item.cost ? ` · ${money.format(item.current_stock * item.cost)} en almacén` : ""}.`}),
                el("p", {className: "leftover-suggestion", text: suggestion}),
            ]),
        ]);
    }

    function renderLeftovers() {
        $("leftoversSummary").textContent = state.items.length
            ? `${plural(state.items.length, "ingrediente", "ingredientes")} con riesgo de perderse o sin salida.`
            : "Nada que aprovechar ahora mismo.";
        const list = $("leftoverList");
        list.replaceChildren();
        if (!state.items.length) {
            list.append(el("p", {className: "empty-state", text: "Todo tu stock está en su sitio: nada por encima del ideal, sin mermas recientes y todo se usa en alguna receta."}));
        }
        state.items.forEach((item) => list.append(leftoverCard(item)));

        $("ideasBar").hidden = !state.aiAvailable || !state.items.length;
        $("ideasSelection").textContent = state.selected.size
            ? `${plural(state.selected.size, "ingrediente elegido", "ingredientes elegidos")}`
            : "Elige ingredientes para pedir ideas";
        $("ideasButton").disabled = !state.selected.size || state.loadingIdeas;
        $("ideasButton").textContent = state.loadingIdeas ? "Pensando ideas..." : "Pedir ideas a la IA";
    }

    $("leftoverList").addEventListener("change", (event) => {
        const checkbox = event.target.closest("[data-select]");
        if (!checkbox) return;
        const itemId = Number(checkbox.dataset.select);
        if (checkbox.checked) {
            if (state.selected.size >= MAX_SELECTION) {
                checkbox.checked = false;
                showAlert(`Como máximo ${MAX_SELECTION} ingredientes a la vez.`, "error");
                return;
            }
            state.selected.add(itemId);
        } else {
            state.selected.delete(itemId);
        }
        renderLeftovers();
    });

    function ideaCard(idea) {
        return el("article", {className: "dish-card idea-card"}, [
            el("div", {className: "dish-card-main"}, [
                el("h3", {text: idea.name}),
                idea.description ? el("p", {className: "dish-description", text: idea.description}) : null,
                idea.why ? el("p", {className: "leftover-suggestion", text: idea.why}) : null,
                el("ul", {className: "idea-ingredients"}, idea.ingredients.map((line) => el("li", {
                    text: `${line.name}: ${quantity(line.quantity, line.unit)}${line.line_cost !== null ? ` · ${money.format(line.line_cost)}` : " · sin coste"}`,
                }))),
            ]),
            el("dl", {className: "costing-figures idea-figures"}, [
                el("dt", {text: "Coste por ración"}),
                el("dd", {text: `${money.format(idea.estimated_cost)}${idea.missing_costs ? " (incompleto)" : ""}`}),
                el("dt", {text: "Precio para un 30 %"}),
                el("dd", {text: idea.suggested_price ? money.format(idea.suggested_price) : "—"}),
            ]),
        ]);
    }

    $("ideasButton").addEventListener("click", async () => {
        if (!state.selected.size || state.loadingIdeas) return;
        state.loadingIdeas = true;
        renderLeftovers();
        try {
            const result = await request("/leftovers/ideas", {
                method: "POST",
                body: JSON.stringify({restaurant_id: state.restaurantId, ingredient_ids: [...state.selected]}),
            });
            $("ideasPanel").hidden = false;
            $("ideaList").replaceChildren(...(result.ideas.length
                ? result.ideas.map(ideaCard)
                : [el("p", {className: "empty-state", text: result.error || "Sin ideas esta vez."})]));
            $("ideasPanel").scrollIntoView({behavior: "smooth", block: "start"});
        } catch (error) {
            showAlert(error.message, "error");
        } finally {
            state.loadingIdeas = false;
            renderLeftovers();
        }
    });

    renderLeftovers();
})();
