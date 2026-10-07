(() => {
    const bootstrapNode = document.getElementById("menuAdminBootstrap");
    if (!bootstrapNode) {
        return;
    }

    const bootstrap = JSON.parse(bootstrapNode.textContent || "{}");
    const state = {
        restaurantId: bootstrap.restaurantId,
        currency: bootstrap.currency || "EUR",
        categories: bootstrap.categories || [],
        dishes: bootstrap.dishes || [],
        editingDishId: null,
        busy: false,
    };

    const api = (path) => `/api/restaurants/${state.restaurantId}${path}`;
    const $ = (id) => document.getElementById(id);

    const alertBox = $("menuAdminAlert");
    const categoryList = $("categoryList");
    const categoryCreateForm = $("categoryCreateForm");
    const dishList = $("dishList");
    const dishSummary = $("dishSummary");
    const dishSearch = $("dishSearch");
    const dishCategoryFilter = $("dishCategoryFilter");
    const showHiddenOnly = $("showHiddenOnly");
    const dishDialog = $("dishDialog");
    const dishForm = $("dishForm");
    const dishFormError = $("dishFormError");
    const dishDialogTitle = $("dishDialogTitle");
    const dishSubmitButton = $("dishSubmitButton");

    $("publicMenuLink").href = bootstrap.publicMenuUrl || "/menu";

    const moneyFormatter = new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: state.currency,
    });

    function formatPrice(value) {
        if (value === null || value === undefined || value === "") {
            return "Sin precio";
        }
        return moneyFormatter.format(Number(value));
    }

    function el(tag, options = {}, children = []) {
        const node = document.createElement(tag);
        if (options.className) node.className = options.className;
        if (options.text !== undefined) node.textContent = options.text;
        if (options.attrs) {
            Object.entries(options.attrs).forEach(([key, value]) => {
                if (value !== false && value !== null && value !== undefined) {
                    node.setAttribute(key, value === true ? "" : String(value));
                }
            });
        }
        children.forEach((child) => child && node.append(child));
        return node;
    }

    let alertTimer = null;
    function showAlert(message, tone = "success") {
        clearTimeout(alertTimer);
        alertBox.textContent = message;
        alertBox.dataset.tone = tone;
        alertBox.hidden = false;
        alertTimer = setTimeout(() => {
            alertBox.hidden = true;
        }, tone === "error" ? 7000 : 3500);
    }

    async function errorMessage(response) {
        try {
            const payload = await response.json();
            if (payload?.error?.message) {
                return payload.error.message;
            }
            if (Array.isArray(payload?.detail) && payload.detail.length) {
                return payload.detail[0].msg.replace(/^Value error, /, "");
            }
        } catch (error) {
            // Fall through to the generic message.
        }
        return "No se pudo guardar el cambio. Inténtalo de nuevo.";
    }

    async function request(path, options = {}) {
        const response = await window.HostAISecurity.fetch(api(path), {
            headers: {"Content-Type": "application/json", Accept: "application/json"},
            ...options,
        });
        if (!response.ok) {
            throw new Error(await errorMessage(response));
        }
        return response.status === 204 ? null : response.json();
    }

    async function reload() {
        const data = await request("/menu-management");
        state.categories = data.categories;
        state.dishes = data.dishes;
        render();
    }

    async function runAction(action, successMessage) {
        if (state.busy) {
            return false;
        }
        state.busy = true;
        document.body.classList.add("is-busy");
        try {
            await action();
            await reload();
            if (successMessage) {
                showAlert(successMessage);
            }
            return true;
        } catch (error) {
            showAlert(error.message, "error");
            return false;
        } finally {
            state.busy = false;
            document.body.classList.remove("is-busy");
        }
    }

    function categoryName(categoryId) {
        return state.categories.find((item) => item.id === categoryId)?.name || "Sin categoría";
    }

    // --- Categories -------------------------------------------------------

    function renderCategories() {
        categoryList.replaceChildren();
        if (!state.categories.length) {
            categoryList.append(el("li", {
                className: "empty-state",
                text: "Todavía no hay categorías. Crea la primera para poder añadir platos.",
            }));
            return;
        }

        state.categories.forEach((category, index) => {
            const isFirst = index === 0;
            const isLast = index === state.categories.length - 1;
            const hasDishes = category.dish_count > 0;

            const nameLabel = el("span", {className: "category-name", text: category.name});
            const count = el("span", {
                className: "category-count",
                text: `${category.dish_count} ${category.dish_count === 1 ? "plato" : "platos"}`,
            });

            const actions = el("div", {className: "row-actions"}, [
                el("button", {
                    className: "icon-action",
                    text: "↑",
                    attrs: {type: "button", "aria-label": `Subir ${category.name}`, disabled: isFirst, "data-move": "up", "data-id": category.id},
                }),
                el("button", {
                    className: "icon-action",
                    text: "↓",
                    attrs: {type: "button", "aria-label": `Bajar ${category.name}`, disabled: isLast, "data-move": "down", "data-id": category.id},
                }),
                el("button", {
                    className: "menu-admin-button is-small",
                    text: "Renombrar",
                    attrs: {type: "button", "data-rename": category.id},
                }),
                el("button", {
                    className: "menu-admin-button is-small is-danger",
                    text: "Borrar",
                    attrs: {
                        type: "button",
                        "data-delete-category": category.id,
                        disabled: hasDishes,
                        title: hasDishes ? "Mueve u oculta sus platos: solo se pueden borrar categorías vacías." : false,
                    },
                }),
            ]);

            categoryList.append(el("li", {className: "category-row", attrs: {"data-category-row": category.id}}, [
                el("div", {className: "category-copy"}, [nameLabel, count]),
                actions,
            ]));
        });
    }

    function startRename(categoryId) {
        const row = categoryList.querySelector(`[data-category-row="${categoryId}"]`);
        const category = state.categories.find((item) => item.id === categoryId);
        if (!row || !category) {
            return;
        }
        const input = el("input", {attrs: {type: "text", maxlength: 120, "aria-label": "Nuevo nombre"}});
        input.value = category.name;
        const form = el("form", {className: "inline-form rename-form"}, [
            input,
            el("button", {className: "menu-admin-button is-small is-primary", text: "Guardar", attrs: {type: "submit"}}),
            el("button", {className: "menu-admin-button is-small", text: "Cancelar", attrs: {type: "button", "data-cancel-rename": ""}}),
        ]);
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const name = input.value.trim();
            if (!name || name === category.name) {
                renderCategories();
                return;
            }
            runAction(
                () => request(`/categories/${categoryId}`, {method: "PATCH", body: JSON.stringify({name})}),
                "Categoría renombrada.",
            );
        });
        row.replaceChildren(form);
        input.focus();
        input.select();
    }

    async function moveCategory(categoryId, direction) {
        const ordered = [...state.categories];
        const index = ordered.findIndex((item) => item.id === categoryId);
        const target = direction === "up" ? index - 1 : index + 1;
        if (index < 0 || target < 0 || target >= ordered.length) {
            return;
        }
        [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
        // Rewrite positions in steps of 10 so every category has a distinct order.
        const updates = ordered
            .map((category, position) => ({category, display_order: position * 10}))
            .filter(({category, display_order}) => category.display_order !== display_order);
        await runAction(async () => {
            for (const {category, display_order} of updates) {
                await request(`/categories/${category.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({display_order}),
                });
            }
        });
    }

    categoryList.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button || button.disabled) {
            return;
        }
        if (button.dataset.move) {
            moveCategory(Number(button.dataset.id), button.dataset.move);
        } else if (button.dataset.rename) {
            startRename(Number(button.dataset.rename));
        } else if (button.dataset.cancelRename !== undefined) {
            renderCategories();
        } else if (button.dataset.deleteCategory) {
            const categoryId = Number(button.dataset.deleteCategory);
            const name = categoryName(categoryId);
            if (window.confirm(`¿Borrar la categoría "${name}"?`)) {
                runAction(
                    () => request(`/categories/${categoryId}`, {method: "DELETE"}),
                    "Categoría borrada.",
                );
            }
        }
    });

    categoryCreateForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const input = categoryCreateForm.elements.name;
        const name = input.value.trim();
        if (!name) {
            return;
        }
        const lastOrder = state.categories.reduce((max, item) => Math.max(max, item.display_order), -10);
        const created = await runAction(
            () => request("/categories", {
                method: "POST",
                body: JSON.stringify({name, display_order: lastOrder + 10}),
            }),
            "Categoría creada.",
        );
        if (created) {
            categoryCreateForm.reset();
        }
    });

    // --- Dishes -----------------------------------------------------------

    function renderCategoryOptions() {
        const selected = dishCategoryFilter.value;
        dishCategoryFilter.replaceChildren(el("option", {text: "Todas las categorías", attrs: {value: "all"}}));
        state.categories.forEach((category) => {
            dishCategoryFilter.append(el("option", {text: category.name, attrs: {value: category.id}}));
        });
        dishCategoryFilter.value = [...dishCategoryFilter.options].some((option) => option.value === selected)
            ? selected
            : "all";

        const formSelect = dishForm.elements.category_id;
        formSelect.replaceChildren();
        state.categories.forEach((category) => {
            formSelect.append(el("option", {text: category.name, attrs: {value: category.id}}));
        });
    }

    function filteredDishes() {
        const query = dishSearch.value.trim().toLocaleLowerCase("es");
        const category = dishCategoryFilter.value;
        // Same order as the public menu: category position first, then the dish's own order.
        const categoryRank = new Map(state.categories.map((item, index) => [item.id, index]));
        return state.dishes
            .slice()
            .sort((a, b) => (categoryRank.get(a.category_id) ?? 0) - (categoryRank.get(b.category_id) ?? 0)
                || a.display_order - b.display_order
                || a.name.localeCompare(b.name, "es"))
            .filter((dish) => {
            if (category !== "all" && dish.category_id !== Number(category)) return false;
            if (showHiddenOnly.checked && dish.is_active) return false;
            if (query && !`${dish.name} ${dish.description} ${dish.ingredients}`.toLocaleLowerCase("es").includes(query)) return false;
            return true;
        });
    }

    function renderDishes() {
        const hiddenCount = state.dishes.filter((dish) => !dish.is_active).length;
        const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
        dishSummary.textContent = state.dishes.length
            ? `${plural(state.dishes.length, "plato", "platos")} · ${plural(hiddenCount, "oculto", "ocultos")}`
            : "Aún no hay platos.";

        dishList.replaceChildren();
        const dishes = filteredDishes();
        if (!dishes.length) {
            dishList.append(el("p", {
                className: "empty-state",
                text: state.dishes.length ? "Ningún plato coincide con el filtro." : "Crea tu primer plato con el botón «Nuevo plato».",
            }));
            return;
        }

        dishes.forEach((dish) => {
            const badges = el("div", {className: "dish-badges"}, [
                el("span", {className: "dish-category", text: categoryName(dish.category_id)}),
                dish.is_active ? null : el("span", {className: "dish-hidden-badge", text: "Oculto"}),
                dish.price === null ? el("span", {className: "dish-warning-badge", text: "Sin precio: no se puede pedir"}) : null,
            ]);

            const card = el("article", {className: `dish-card${dish.is_active ? "" : " is-hidden"}`}, [
                el("div", {className: "dish-card-main"}, [
                    badges,
                    el("h3", {text: dish.name}),
                    dish.description ? el("p", {className: "dish-description", text: dish.description}) : null,
                    dish.allergens ? el("p", {className: "dish-allergens", text: `Alérgenos: ${dish.allergens}`}) : null,
                ]),
                el("div", {className: "dish-card-side"}, [
                    el("strong", {className: "dish-price", text: formatPrice(dish.price)}),
                    el("div", {className: "row-actions"}, [
                        el("button", {
                            className: "menu-admin-button is-small",
                            text: dish.is_active ? "Ocultar" : "Mostrar",
                            attrs: {type: "button", "data-toggle-dish": dish.id},
                        }),
                        el("button", {
                            className: "menu-admin-button is-small is-primary",
                            text: "Editar",
                            attrs: {type: "button", "data-edit-dish": dish.id},
                        }),
                    ]),
                ]),
            ]);
            dishList.append(card);
        });
    }

    function openDishDialog(dish = null) {
        if (!state.categories.length) {
            showAlert("Crea primero una categoría para poder añadir platos.", "error");
            categoryCreateForm.elements.name.focus();
            return;
        }
        state.editingDishId = dish ? dish.id : null;
        dishForm.reset();
        dishFormError.hidden = true;
        dishDialogTitle.textContent = dish ? "Editar plato" : "Nuevo plato";
        dishSubmitButton.textContent = dish ? "Guardar cambios" : "Crear plato";

        const fields = dishForm.elements;
        const filterCategory = dishCategoryFilter.value;
        fields.name.value = dish?.name || "";
        fields.category_id.value = String(
            dish?.category_id || (filterCategory !== "all" ? filterCategory : state.categories[0].id),
        );
        fields.price.value = dish?.price ? dish.price.replace(".", ",") : "";
        fields.description.value = dish?.description || "";
        fields.ingredients.value = dish?.ingredients || "";
        fields.allergens.value = dish?.allergens || "";
        fields.image.value = dish?.image || "";
        fields.display_order.value = dish?.display_order ?? 0;
        fields.is_active.checked = dish ? dish.is_active : true;

        dishDialog.showModal();
        fields.name.focus();
    }

    function readDishForm() {
        const fields = dishForm.elements;
        const rawPrice = fields.price.value.trim().replace(/\s|€/g, "").replace(",", ".");
        if (rawPrice && !/^\d+(\.\d{1,2})?$/.test(rawPrice)) {
            throw new Error("El precio debe ser un número con hasta dos decimales, por ejemplo 12,50.");
        }
        const name = fields.name.value.trim();
        if (!name) {
            throw new Error("El plato necesita un nombre.");
        }
        return {
            name,
            category_id: Number(fields.category_id.value),
            price: rawPrice || null,
            description: fields.description.value.trim(),
            ingredients: fields.ingredients.value.trim(),
            allergens: fields.allergens.value.trim(),
            image: fields.image.value.trim(),
            display_order: Number(fields.display_order.value || 0),
            is_active: fields.is_active.checked,
        };
    }

    dishForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        let payload;
        try {
            payload = readDishForm();
        } catch (error) {
            dishFormError.textContent = error.message;
            dishFormError.hidden = false;
            return;
        }
        if (state.busy) {
            return;
        }
        state.busy = true;
        dishSubmitButton.disabled = true;
        dishFormError.hidden = true;
        const isEdit = state.editingDishId !== null;
        try {
            await request(isEdit ? `/dishes/${state.editingDishId}` : "/dishes", {
                method: isEdit ? "PATCH" : "POST",
                body: JSON.stringify(payload),
            });
            dishDialog.close();
            await reload();
            showAlert(isEdit ? "Plato actualizado." : "Plato creado.");
        } catch (error) {
            dishFormError.textContent = error.message;
            dishFormError.hidden = false;
        } finally {
            state.busy = false;
            dishSubmitButton.disabled = false;
        }
    });

    dishDialog.addEventListener("click", (event) => {
        if (event.target.closest("[data-close-dialog]")) {
            dishDialog.close();
        }
    });

    $("newDishButton").addEventListener("click", () => openDishDialog());

    dishList.addEventListener("click", (event) => {
        const button = event.target.closest("button");
        if (!button) {
            return;
        }
        if (button.dataset.editDish) {
            openDishDialog(state.dishes.find((dish) => dish.id === Number(button.dataset.editDish)));
        } else if (button.dataset.toggleDish) {
            const dish = state.dishes.find((item) => item.id === Number(button.dataset.toggleDish));
            if (!dish) return;
            runAction(
                () => request(`/dishes/${dish.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({is_active: !dish.is_active}),
                }),
                dish.is_active ? `«${dish.name}» oculto de la carta.` : `«${dish.name}» vuelve a la carta.`,
            );
        }
    });

    [dishSearch, dishCategoryFilter, showHiddenOnly].forEach((control) => {
        control.addEventListener("input", renderDishes);
    });

    function render() {
        renderCategories();
        renderCategoryOptions();
        renderDishes();
    }

    render();
})();
