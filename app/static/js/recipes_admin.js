(() => {
    const {el, readBootstrap, createAlert, createRequester, createActionRunner, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("recipesAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const UNIT_LABELS = {g: "g", kg: "kg", ml: "ml", l: "l", unit: "ud."};
    const TARGET_KEY = "hostai:food-cost-target";

    const readTarget = () => {
        try {
            const stored = Number(window.localStorage.getItem(TARGET_KEY));
            return stored > 0 && stored < 100 ? stored : 30;
        } catch (error) {
            return 30;
        }
    };

    const state = {
        restaurantId: bootstrap.restaurantId,
        vat: bootstrap.vat_percentage ?? 10,
        target: readTarget(),
        categories: bootstrap.categories || [],
        ingredients: bootstrap.ingredients || [],
        dishes: bootstrap.dishes || [],
        openDishId: null,
        submitting: false,
    };

    const $ = (id) => document.getElementById(id);
    const dishList = $("dishList");
    const recipeDialog = $("recipeDialog");
    const lineForm = $("lineCreateForm");

    const showAlert = createAlert($("menuAdminAlert"));
    const recipesRequest = createRequester(`/api/restaurants/${state.restaurantId}`);
    const inventoryRequest = createRequester("/api/inventory");
    const money = new Intl.NumberFormat("es-ES", {style: "currency", currency: bootstrap.currency || "EUR"});
    const number = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3});
    // Editable fields: no thousands separator, or "10.000" would read back as 10.
    const inputNumber = new Intl.NumberFormat("es-ES", {maximumFractionDigits: 3, useGrouping: false});
    const percent = (value) => (value === null || value === undefined ? "—" : `${number.format(Math.round(value * 10) / 10)} %`);
    const unitLabel = (unit) => UNIT_LABELS[unit] || unit;

    async function reload() {
        const data = await recipesRequest("/recipes");
        state.dishes = data.dishes;
        state.ingredients = data.ingredients;
        state.vat = data.vat_percentage;
        render();
    }

    const runAction = createActionRunner({reload, showAlert});
    const dishById = (dishId) => state.dishes.find((dish) => dish.dish_id === dishId);
    const categoryName = (categoryId) => state.categories.find((category) => category.id === categoryId)?.name || "";

    function parseAmount(raw, label, {positive = false, max = null} = {}) {
        const text = String(raw ?? "").trim().replace(/\s|%|€/g, "").replace(",", ".");
        if (!/^\d+(\.\d+)?$/.test(text)) {
            throw new Error(`${label} debe ser un número, por ejemplo 0,15.`);
        }
        const value = Number(text);
        if (positive && value <= 0) throw new Error(`${label} tiene que ser mayor que cero.`);
        if (max !== null && value > max) throw new Error(`${label} no puede ser mayor que ${max}.`);
        return value;
    }

    // ok | warn (within 5 points over target) | over | incomplete
    function costStatus(dish) {
        if (!dish.has_recipe || dish.missing_costs || dish.food_cost_percentage === null) return "incomplete";
        if (dish.food_cost_percentage <= state.target) return "ok";
        if (dish.food_cost_percentage <= state.target + 5) return "warn";
        return "over";
    }

    const suggestedPrice = (dish) => (dish.total_cost > 0
        ? dish.total_cost / (state.target / 100) * (1 + state.vat / 100)
        : null);

    // --- Settings & summary -------------------------------------------------------

    $("vatInput").value = String(state.vat).replace(".", ",");
    $("targetInput").value = String(state.target).replace(".", ",");

    $("vatForm").addEventListener("submit", (event) => {
        event.preventDefault();
        let vat;
        try {
            vat = parseAmount($("vatInput").value, "El IVA", {max: 30});
        } catch (error) {
            showAlert(error.message, "error");
            return;
        }
        runAction(
            () => recipesRequest("", {method: "PATCH", body: JSON.stringify({vat_percentage: vat})}),
            `IVA actualizado al ${number.format(vat)} %. Escandallos recalculados.`,
        );
    });

    $("targetInput").addEventListener("change", () => {
        try {
            state.target = parseAmount($("targetInput").value, "El objetivo", {positive: true, max: 99});
            try { window.localStorage.setItem(TARGET_KEY, String(state.target)); } catch (error) { /* private mode */ }
            render();
        } catch (error) {
            showAlert(error.message, "error");
            $("targetInput").value = String(state.target).replace(".", ",");
        }
    });

    function renderSummary() {
        const complete = state.dishes.filter((dish) => costStatus(dish) !== "incomplete");
        const average = complete.length
            ? complete.reduce((sum, dish) => sum + dish.food_cost_percentage, 0) / complete.length
            : null;
        $("summaryAverage").textContent = percent(average);
        $("summaryOver").textContent = state.dishes.filter((dish) => ["over", "warn"].includes(costStatus(dish))).length;
        $("summaryIncomplete").textContent = state.dishes.filter((dish) => costStatus(dish) === "incomplete").length;
    }

    // --- Dish list ---------------------------------------------------------------

    const STATUS_BADGES = {
        ok: ["stock-badge is-ok", "Dentro del objetivo"],
        warn: ["stock-badge is-warning", "Algo por encima"],
        over: ["stock-badge is-critical", "Por encima del objetivo"],
        incomplete: ["dish-hidden-badge", "Incompleto"],
    };

    function dishCard(dish) {
        const status = costStatus(dish);
        const [badgeClass, badgeText] = STATUS_BADGES[status];
        const notes = [];
        if (!dish.has_recipe) notes.push("Sin receta: no descuenta stock ni tiene escandallo.");
        else if (dish.missing_costs) notes.push("Algún ingrediente no tiene coste.");
        if (!dish.sale_price) notes.push("Sin precio de venta.");

        const figures = dish.has_recipe ? [
            ["Coste", money.format(dish.total_cost)],
            ["Precio", dish.sale_price ? money.format(dish.sale_price) : "—"],
            ["Materia prima", percent(dish.food_cost_percentage)],
            ["Margen sin IVA", dish.net_margin !== null && dish.sale_price ? money.format(dish.net_margin) : "—"],
        ] : [["Precio", dish.sale_price ? money.format(dish.sale_price) : "—"]];

        return el("article", {className: `dish-card costing-card is-${status}${dish.is_active ? "" : " is-hidden"}`}, [
            el("div", {className: "dish-card-main"}, [
                el("div", {className: "dish-badges"}, [
                    el("span", {className: badgeClass, text: badgeText}),
                    categoryName(dish.category_id) ? el("span", {className: "dish-category", text: categoryName(dish.category_id)}) : null,
                    dish.is_active ? null : el("span", {className: "dish-hidden-badge", text: "Oculto en carta"}),
                ]),
                el("h3", {text: dish.dish_name}),
                el("dl", {className: "costing-figures"}, figures.flatMap(([label, value]) => [
                    el("dt", {text: label}),
                    el("dd", {text: value}),
                ])),
                notes.length ? el("p", {className: "dish-allergens", text: notes.join(" ")}) : null,
            ]),
            el("div", {className: "dish-card-side"}, [
                el("button", {
                    className: `menu-admin-button is-small${dish.has_recipe ? "" : " is-primary"}`,
                    text: dish.has_recipe ? `Receta (${dish.ingredients_breakdown.length})` : "Crear receta",
                    attrs: {type: "button", "data-open-recipe": dish.dish_id},
                }),
            ]),
        ]);
    }

    function renderDishes() {
        const query = $("dishSearch").value.trim().toLocaleLowerCase("es");
        const filter = $("dishFilter").value;
        const rank = {over: 0, warn: 1, incomplete: 2, ok: 3};
        const dishes = state.dishes
            .filter((dish) => {
                const status = costStatus(dish);
                if (filter === "over" && !["over", "warn"].includes(status)) return false;
                if (filter === "incomplete" && status !== "incomplete") return false;
                return !query || dish.dish_name.toLocaleLowerCase("es").includes(query);
            })
            .sort((a, b) => rank[costStatus(a)] - rank[costStatus(b)] || a.dish_name.localeCompare(b.dish_name, "es"));

        dishList.replaceChildren();
        if (!dishes.length) {
            dishList.append(el("p", {
                className: "empty-state",
                text: state.dishes.length ? "Ningún plato coincide con el filtro." : "Crea platos en «Carta» para poder escribir sus recetas.",
            }));
            return;
        }
        dishes.forEach((dish) => dishList.append(dishCard(dish)));
    }

    // --- Recipe dialog -------------------------------------------------------------

    function renderRecipe() {
        const dish = dishById(state.openDishId);
        if (!dish) return;
        $("recipeDialogTitle").textContent = dish.dish_name;
        $("recipeDialogMeta").textContent = [
            categoryName(dish.category_id),
            dish.sale_price ? `${money.format(dish.sale_price)} en carta` : "sin precio",
        ].filter(Boolean).join(" · ");

        const warnings = [];
        if (dish.ingredients_breakdown.some((line) => line.missing_cost)) {
            warnings.push("Hay ingredientes sin coste: el escandallo se queda corto. Añádelo en «Inventario».");
        }
        // Classic data-entry slip: item stored in grams, cost typed per kilo.
        dish.ingredients_breakdown
            .filter((line) => dish.sale_price && line.line_cost > dish.sale_price)
            .forEach((line) => warnings.push(
                `${line.ingredient_name} cuesta más que el plato entero (${money.format(line.line_cost)}). `
                + `¿Su coste está por kilo y el ingrediente se mide en ${unitLabel(line.ingredient_unit)}? Revísalo en «Inventario».`,
            ));
        if (dish.ingredients_breakdown.some((line) => line.unit_mismatch)) {
            warnings.push("Alguna línea usa una unidad distinta a la de su ingrediente: su coste no es fiable. Quítala y vuelve a añadirla.");
        }
        $("recipeWarnings").replaceChildren(...warnings.map((text) => el("p", {className: "menu-admin-notice", text})));

        const lines = $("recipeLines");
        lines.replaceChildren();
        if (!dish.ingredients_breakdown.length) {
            lines.append(el("p", {className: "empty-state", text: "Esta receta está vacía. Añade el primer ingrediente abajo."}));
        }
        dish.ingredients_breakdown.forEach((line) => {
            const share = dish.total_cost > 0 ? (line.line_cost / dish.total_cost) * 100 : 0;
            const quantityInput = el("input", {attrs: {type: "text", inputmode: "decimal", "aria-label": `Cantidad de ${line.ingredient_name}`, "data-line-field": "quantity", "data-line-id": line.recipe_line_id}});
            quantityInput.value = inputNumber.format(line.quantity);
            const yieldInput = el("input", {attrs: {type: "text", inputmode: "decimal", "aria-label": `Aprovechamiento de ${line.ingredient_name}`, "data-line-field": "yield_percentage", "data-line-id": line.recipe_line_id}});
            yieldInput.value = inputNumber.format(line.yield_percentage);

            const grossNote = line.yield_percentage < 100
                ? `Salen del almacén ${number.format(line.gross_quantity)} ${unitLabel(line.ingredient_unit)}`
                : null;

            lines.append(el("article", {className: `recipe-line${line.unit_mismatch ? " has-warning" : ""}`}, [
                el("div", {className: "recipe-line-name"}, [
                    el("strong", {text: line.ingredient_name}),
                    el("span", {text: line.missing_cost ? "Sin coste" : `${money.format(line.unit_cost)} / ${unitLabel(line.ingredient_unit)}`}),
                ]),
                el("label", {className: "recipe-line-field"}, [
                    el("span", {text: `En el plato (${unitLabel(line.unit)})`}),
                    quantityInput,
                ]),
                el("label", {className: "recipe-line-field"}, [
                    el("span", {text: "Aprovech."}),
                    el("div", {className: "input-suffix"}, [yieldInput, el("span", {text: "%"})]),
                ]),
                el("div", {className: "recipe-line-cost"}, [
                    el("strong", {text: money.format(line.line_cost)}),
                    el("span", {text: `${percent(share)} del coste`}),
                    grossNote ? el("small", {text: grossNote}) : null,
                ]),
                el("button", {
                    className: "icon-action recipe-line-remove",
                    text: "×",
                    attrs: {type: "button", "aria-label": `Quitar ${line.ingredient_name}`, "data-remove-line": line.recipe_line_id},
                }),
            ]));
        });

        // Ingredient picker: only those not already in the recipe.
        const used = new Set(dish.ingredients_breakdown.map((line) => line.ingredient_id));
        const select = lineForm.elements.inventory_item_id;
        const available = state.ingredients.filter((item) => !used.has(item.id));
        select.replaceChildren(...available.map((item) => el("option", {
            text: `${item.name} (${unitLabel(item.unit)})${item.cost ? "" : " · sin coste"}`,
            attrs: {value: item.id},
        })));
        lineForm.querySelector('button[type="submit"]').disabled = !available.length;
        updateAddLabel();

        const suggested = suggestedPrice(dish);
        const totals = [
            ["Coste por ración", money.format(dish.total_cost)],
            ["Precio en carta (con IVA)", dish.sale_price ? money.format(dish.sale_price) : "—"],
            [`Precio sin IVA (${number.format(state.vat)} %)`, dish.price_without_vat ? money.format(dish.price_without_vat) : "—"],
            ["Coste de materia prima", percent(dish.food_cost_percentage)],
            ["Margen sin IVA", dish.sale_price ? `${money.format(dish.net_margin)} (${percent(dish.net_margin_percentage)})` : "—"],
            [`Precio para un ${number.format(state.target)} % de coste`, suggested ? `${money.format(suggested)} con IVA` : "—"],
        ];
        $("costingTotals").replaceChildren(...totals.flatMap(([label, value]) => [el("dt", {text: label}), el("dd", {text: value})]));
    }

    function updateAddLabel() {
        const item = state.ingredients.find((ingredient) => ingredient.id === Number(lineForm.elements.inventory_item_id.value));
        $("addQuantityLabel").textContent = item ? `Cantidad en el plato (${unitLabel(item.unit)})` : "Cantidad en el plato";
    }

    function setLineError(message) {
        $("lineFormError").textContent = message || "";
        $("lineFormError").hidden = !message;
    }

    function openRecipe(dishId) {
        state.openDishId = dishId;
        lineForm.reset();
        setLineError(null);
        renderRecipe();
        recipeDialog.showModal();
    }

    lineForm.elements.inventory_item_id.addEventListener("change", updateAddLabel);

    lineForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const dish = dishById(state.openDishId);
        const item = state.ingredients.find((ingredient) => ingredient.id === Number(lineForm.elements.inventory_item_id.value));
        if (!dish || !item) return;
        let payload;
        try {
            payload = {
                restaurant_id: state.restaurantId,
                dish_id: dish.dish_id,
                inventory_item_id: item.id,
                unit: item.unit,
                quantity: parseAmount(lineForm.elements.quantity.value, "La cantidad", {positive: true}),
                yield_percentage: parseAmount(lineForm.elements.yield_percentage.value, "El aprovechamiento", {positive: true, max: 100}),
            };
        } catch (error) {
            setLineError(error.message);
            return;
        }
        if (state.submitting || runAction.isBusy()) return;
        state.submitting = true;
        setLineError(null);
        try {
            await inventoryRequest("/dish-ingredients", {method: "POST", body: JSON.stringify(payload)});
            lineForm.reset();
            await reload();
            showAlert(`${item.name} añadido a ${dish.dish_name}.`);
        } catch (error) {
            setLineError(error.message);
        } finally {
            state.submitting = false;
        }
    });

    $("recipeLines").addEventListener("change", (event) => {
        const input = event.target.closest("[data-line-field]");
        if (!input) return;
        const field = input.dataset.lineField;
        let value;
        try {
            value = field === "quantity"
                ? parseAmount(input.value, "La cantidad", {positive: true})
                : parseAmount(input.value, "El aprovechamiento", {positive: true, max: 100});
        } catch (error) {
            showAlert(error.message, "error");
            renderRecipe();
            return;
        }
        runAction(
            () => inventoryRequest(`/dish-ingredients/${input.dataset.lineId}`, {method: "PATCH", body: JSON.stringify({[field]: value})}),
            "Receta actualizada.",
        );
    });

    $("recipeLines").addEventListener("click", (event) => {
        const button = event.target.closest("[data-remove-line]");
        if (!button) return;
        const dish = dishById(state.openDishId);
        const line = dish?.ingredients_breakdown.find((item) => item.recipe_line_id === Number(button.dataset.removeLine));
        if (!line || !window.confirm(`¿Quitar ${line.ingredient_name} de ${dish.dish_name}?`)) return;
        runAction(
            () => inventoryRequest(`/dish-ingredients/${line.recipe_line_id}`, {method: "DELETE"}),
            `${line.ingredient_name} quitado de la receta.`,
        );
    });

    recipeDialog.addEventListener("click", (event) => {
        if (event.target.closest("[data-close-dialog]")) recipeDialog.close();
    });
    recipeDialog.addEventListener("close", () => {
        state.openDishId = null;
    });

    dishList.addEventListener("click", (event) => {
        const button = event.target.closest("[data-open-recipe]");
        if (button) openRecipe(Number(button.dataset.openRecipe));
    });

    document.querySelectorAll("[data-summary-filter]").forEach((button) => {
        button.addEventListener("click", () => {
            $("dishFilter").value = button.dataset.summaryFilter;
            renderDishes();
            dishList.scrollIntoView({behavior: "smooth", block: "start"});
        });
    });
    [$("dishSearch"), $("dishFilter")].forEach((control) => control.addEventListener("input", renderDishes));

    function render() {
        renderSummary();
        renderDishes();
        if (state.openDishId !== null && recipeDialog.open) renderRecipe();
    }

    render();
})();
