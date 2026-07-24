const categoriesContainer = document.getElementById("categories");
const dishesContainer = document.getElementById("dishes");
const languageSelect = document.getElementById("languageSelect");
const menuSearch = document.getElementById("menuSearch");
const menuState = document.getElementById("menuState");

const categories = window.menuData?.categories || [];
const dishes = window.menuData?.dishes || [];
const restaurant = window.menuData?.restaurant || {};
const restaurantId = window.menuData?.restaurantId || 1;

let activeCategoryId = null;
let searchQuery = "";
let searchTrackingTimer = null;

const trackedDishViews = new Set();

const hasMenuShell = Boolean(categoriesContainer && dishesContainer);

function formatPrice(price) {
    return new Intl.NumberFormat("es-ES", {
        style: "currency",
        currency: restaurant.currency || "EUR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(Number(price || 0));
}

function applyRestaurantBranding() {
    if (restaurant.primary_color) {
        document.documentElement.style.setProperty("--restaurant-primary", restaurant.primary_color);
    }
    if (restaurant.accent_color) {
        document.documentElement.style.setProperty("--restaurant-accent", restaurant.accent_color);
    }
    if (languageSelect && restaurant.default_language) {
        languageSelect.value = restaurant.default_language;
    }
}

function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = text;
    return element;
}

function currentLanguage() {
    return languageSelect?.value || null;
}

function trackEvent(eventType, payload = {}) {
    const metadata = {
        page: "menu",
        source: "public_menu",
        ...payload.metadata,
    };

    window.HostAISecurity.fetch("/api/analytics/events", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        keepalive: true,
        body: JSON.stringify({
            restaurant_id: restaurantId,
            event_type: eventType,
            dish_id: payload.dishId || null,
            language: payload.language || currentLanguage(),
            metadata,
        }),
    }).catch(() => {});
}

function trackDishView(dish) {
    if (trackedDishViews.has(dish.id)) {
        return;
    }

    trackedDishViews.add(dish.id);
    trackEvent("dish_view", {
        dishId: dish.id,
        metadata: {
            dish_name: dish.name,
            category_id: dish.category_id,
        },
    });
}

function scheduleSearchTracking(query) {
    clearTimeout(searchTrackingTimer);

    const normalizedQuery = query.trim();
    if (normalizedQuery.length < 2) {
        return;
    }

    searchTrackingTimer = setTimeout(() => {
        trackEvent("search", {
            metadata: {
                search_query: normalizedQuery,
            },
        });
    }, 450);
}

function renderCategories() {
    if (!categoriesContainer) {
        return;
    }
    categoriesContainer.replaceChildren();

    const allButton = document.createElement("button");
    allButton.className = "category-button";
    allButton.type = "button";
    allButton.textContent = "Todos";
    allButton.setAttribute("aria-pressed", String(activeCategoryId === null));
    if (activeCategoryId === null) {
        allButton.classList.add("active");
    }
    allButton.addEventListener("click", () => {
        activeCategoryId = null;
        renderCategories();
        renderDishes();
    });
    categoriesContainer.appendChild(allButton);

    categories.forEach((category) => {
        const button = document.createElement("button");
        button.className = "category-button";
        button.type = "button";
        button.textContent = category.name;
        button.setAttribute("aria-pressed", String(category.id === activeCategoryId));

        if (category.id === activeCategoryId) {
            button.classList.add("active");
        }

        button.addEventListener("click", () => {
            activeCategoryId = category.id;
            renderCategories();
            renderDishes();
        });

        categoriesContainer.appendChild(button);
    });
}

function buildMetaItem(label, value) {
    const item = document.createElement("p");
    const title = document.createElement("strong");
    title.textContent = label;
    item.append(title, document.createTextNode(value || "No indicado"));
    return item;
}

function buildAllergenBadges(value) {
    const wrapper = document.createElement("div");
    wrapper.className = "allergen-group";
    const title = document.createElement("strong");
    title.textContent = "Alergenos";
    wrapper.appendChild(title);

    const allergens = String(value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);

    if (!allergens.length) {
        wrapper.appendChild(createTextElement("span", "allergen-badge empty", "No indicado"));
        return wrapper;
    }

    allergens.forEach((allergen) => {
        wrapper.appendChild(createTextElement("span", "allergen-badge", allergen));
    });
    return wrapper;
}

function buildDishImage(dish) {
    const media = document.createElement("div");
    media.className = "dish-media";

    if (!dish.image) {
        media.appendChild(createTextElement("div", "dish-placeholder", "Sin imagen"));
        return media;
    }

    const image = document.createElement("img");
    image.className = "dish-image";
    image.src = dish.image;
    image.alt = dish.name;
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => {
        media.replaceChildren(createTextElement("div", "dish-placeholder", "Imagen no disponible"));
    });
    media.appendChild(image);
    return media;
}

function buildDishCard(dish) {
    const card = document.createElement("article");
    card.className = "dish-card";

    const content = document.createElement("div");
    content.className = "dish-content";

    const titleRow = document.createElement("div");
    titleRow.className = "dish-title-row";
    titleRow.append(
        createTextElement("h3", "", dish.name),
        createTextElement("span", "price", formatPrice(dish.price)),
    );

    const meta = document.createElement("div");
    meta.className = "dish-meta";
    meta.append(
        buildMetaItem("Ingredientes", dish.ingredients),
        buildAllergenBadges(dish.allergens),
    );

    const output = createTextElement("p", "translation-output", "");
    output.hidden = true;

    const button = document.createElement("button");
    button.className = "translate-button";
    button.type = "button";
    button.textContent = "Traducir";
    button.addEventListener("click", () => translateDish(dish.id, button, output));

    const footer = document.createElement("div");
    footer.className = "dish-footer";
    footer.append(output, button);

    content.append(
        titleRow,
        createTextElement("p", "dish-description", dish.description || "Sin descripcion disponible."),
        meta,
        footer,
    );

    card.append(buildDishImage(dish), content);
    return card;
}

function renderDishes() {
    if (!dishesContainer) {
        return;
    }
    dishesContainer.replaceChildren();
    hideMenuState();

    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filteredDishes = dishes.filter((dish) => {
        const matchesCategory = activeCategoryId === null || dish.category_id === activeCategoryId;
        const haystack = [
            dish.name,
            dish.description,
            dish.ingredients,
            dish.allergens,
        ].join(" ").toLowerCase();
        return matchesCategory && (!normalizedQuery || haystack.includes(normalizedQuery));
    });

    if (filteredDishes.length === 0) {
        showMenuState("No hay platos disponibles para este filtro.");
        return;
    }

    filteredDishes.forEach((dish) => {
        dishesContainer.appendChild(buildDishCard(dish));
        trackDishView(dish);
    });
}

async function translateDish(dishId, button, output) {
    const lang = languageSelect?.value || "en";

    if (!lang) {
        return;
    }

    button.disabled = true;
    button.textContent = "Traduciendo...";
    output.hidden = true;

    try {
        trackEvent("translation_request", {
            dishId,
            language: lang,
        });
        const response = await window.HostAISecurity.fetch(`/ai/translate-dish/${dishId}?lang=${encodeURIComponent(lang)}`);
        const data = await response.json();

        if (!response.ok || data.error) {
            output.textContent = data.error || "No se pudo traducir el plato.";
            output.hidden = false;
            return;
        }

        output.textContent = `${data.name}: ${data.description}`;
        output.hidden = false;
    } catch {
        output.textContent = "No se pudo conectar con el servicio de traduccion.";
        output.hidden = false;
    } finally {
        button.disabled = false;
        button.textContent = "Traducir";
    }
}

function showMenuState(message) {
    if (!menuState) {
        return;
    }
    menuState.textContent = message;
    menuState.hidden = false;
}

function hideMenuState() {
    if (!menuState) {
        return;
    }
    menuState.textContent = "";
    menuState.hidden = true;
}

menuSearch?.addEventListener("input", (event) => {
    searchQuery = event.target.value;
    renderDishes();
    scheduleSearchTracking(searchQuery);
});

languageSelect?.addEventListener("change", () => {
    trackEvent("language_change", {
        language: currentLanguage(),
    });
});

if (hasMenuShell) {
    applyRestaurantBranding();
    showMenuState("Cargando carta...");
    trackEvent("menu_view", {
        metadata: {
            user_agent: navigator.userAgent,
        },
    });

    if (categories.length > 0 || dishes.length > 0) {
        renderCategories();
        renderDishes();
    } else {
        categoriesContainer.appendChild(createTextElement("p", "empty-message", "No hay categorias disponibles."));
        dishesContainer.replaceChildren();
        showMenuState("Este restaurante aun no tiene platos publicados.");
    }
}
