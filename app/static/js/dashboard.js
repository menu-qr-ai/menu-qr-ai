const dashboardRoot = document.querySelector(".dashboard-shell");
const dashboardState = document.getElementById("dashboardState");
const dashboardMeta = document.getElementById("dashboardMeta");
const dashboardUpdatedAt = document.getElementById("dashboardUpdatedAt");
const demoSeedCta = document.getElementById("demoSeedCta");
const refreshButton = document.getElementById("refreshDashboard");
const restaurantSelect = document.getElementById("restaurantSelect");
const rangeButtons = Array.from(document.querySelectorAll("[data-range-option]"));

let activeRange = dashboardRoot?.dataset.range || "30d";

function numberFormat(value) {
    return new Intl.NumberFormat("es-ES").format(Number(value || 0));
}

function showState(message, visible = true, tone = "neutral") {
    dashboardState.textContent = message;
    dashboardState.dataset.tone = tone;
    dashboardState.classList.toggle("is-visible", visible);
}

function setLoading(isLoading) {
    dashboardRoot.classList.toggle("is-loading", isLoading);
    refreshButton.disabled = isLoading;
}

function setActiveRange(range) {
    activeRange = range;
    rangeButtons.forEach((button) => {
        const isActive = button.dataset.rangeOption === range;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", String(isActive));
    });
}

function setKpis(summary) {
    Object.entries(summary).forEach(([key, value]) => {
        const node = document.querySelector(`[data-kpi="${key}"]`);
        if (!node) {
            return;
        }
        node.textContent = typeof value === "number" ? numberFormat(value) : value || "Sin datos";
    });
}

function emptyRow(message) {
    const element = document.createElement("div");
    element.className = "empty-row";
    element.textContent = message;
    return element;
}

function badge(text) {
    const element = document.createElement("span");
    element.className = "metric-badge";
    element.textContent = text;
    return element;
}

function metricRow(label, value, detail = "", badgeText = "") {
    const row = document.createElement("div");
    row.className = "metric-row";

    const copy = document.createElement("div");
    const labelNode = document.createElement("div");
    labelNode.className = "metric-value";
    labelNode.textContent = label;
    const detailNode = document.createElement("div");
    detailNode.className = "metric-label";
    detailNode.textContent = detail;
    copy.append(labelNode, detailNode);

    const valueWrap = document.createElement("div");
    valueWrap.className = "metric-side";
    const valueNode = document.createElement("strong");
    valueNode.className = "metric-value";
    valueNode.textContent = numberFormat(value);
    valueWrap.appendChild(valueNode);
    if (badgeText) {
        valueWrap.appendChild(badge(badgeText));
    }

    row.append(copy, valueWrap);
    return row;
}

function renderMetricList(containerId, items, emptyMessage, mapper) {
    const container = document.getElementById(containerId);
    container.replaceChildren();
    if (!items.length) {
        container.appendChild(emptyRow(emptyMessage));
        return;
    }
    items.forEach((item) => container.appendChild(mapper(item)));
}

function renderRecentEvents(events) {
    const container = document.getElementById("recentEvents");
    container.replaceChildren();
    if (!events.length) {
        container.appendChild(emptyRow("Todavia no hay actividad reciente."));
        return;
    }
    events.forEach((event) => {
        const row = document.createElement("div");
        row.className = "event-row";

        const copy = document.createElement("div");
        const type = document.createElement("div");
        type.className = "event-type";
        type.textContent = event.event_type;
        const meta = document.createElement("div");
        meta.className = "event-meta";
        meta.textContent = [
            event.language ? `Idioma ${event.language}` : "",
            event.dish_id ? `Plato #${event.dish_id}` : "",
        ].filter(Boolean).join(" - ") || "Evento general";
        copy.append(type, meta);

        const time = document.createElement("time");
        time.className = "event-meta";
        time.dateTime = event.created_at;
        time.textContent = new Date(event.created_at).toLocaleString("es-ES");

        row.append(copy, time);
        container.appendChild(row);
    });
}

function renderInsights(insights) {
    const container = document.getElementById("insights");
    container.replaceChildren();
    insights.forEach((insight) => {
        const card = document.createElement("article");
        card.className = `insight-card ${insight.level || "info"}`;
        const title = document.createElement("strong");
        title.textContent = insight.title;
        const message = document.createElement("p");
        message.textContent = insight.message;
        card.append(title, message);
        container.appendChild(card);
    });
}

function renderMiniBars(containerId, items, valueKey, labelKey) {
    const container = document.getElementById(containerId);
    container.replaceChildren();
    const max = Math.max(...items.map((item) => Number(item[valueKey] || 0)), 1);
    if (!items.length) {
        container.appendChild(emptyRow("Sin datos para graficar."));
        return;
    }
    items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "chart-bar";
        const label = document.createElement("span");
        label.textContent = item[labelKey];
        const bar = document.createElement("i");
        bar.style.width = `${Math.max((Number(item[valueKey] || 0) / max) * 100, 4)}%`;
        const value = document.createElement("strong");
        value.textContent = numberFormat(item[valueKey]);
        row.append(label, bar, value);
        container.appendChild(row);
    });
}

function renderViewsChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.views = data.events_by_day;
    renderMiniBars("viewsChart", data.events_by_day, "total_events", "date");
}

function renderLanguagesChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.languages = data.languages;
    renderMiniBars("languagesChart", data.languages, "count", "language");
}

function renderTopDishesChart(data) {
    window.dashboardCharts = window.dashboardCharts || {};
    window.dashboardCharts.topDishes = data.top_dishes;
    renderMiniBars("topDishesChart", data.top_dishes, "views", "name");
}

function renderDashboard(data) {
    setKpis(data.summary);
    const totalEvents = data.events_by_day.reduce((total, day) => total + day.total_events, 0);
    dashboardMeta.textContent = `Rango: ${data.range} - Eventos: ${numberFormat(totalEvents)}`;
    if (dashboardUpdatedAt) {
        dashboardUpdatedAt.textContent = `Actualizado ${new Date().toLocaleString("es-ES")}`;
    }
    demoSeedCta.hidden = totalEvents > 0;
    renderMetricList("topDishes", data.top_dishes, "Todavia no hay platos vistos.", (dish) =>
        metricRow(dish.name, dish.views, dish.dish_id ? `ID ${dish.dish_id}` : "Sin plato asociado"),
    );
    renderMetricList("topSearches", data.top_searches, "Todavia no hay busquedas.", (search) =>
        metricRow(search.query, search.count, "busqueda registrada"),
    );
    renderMetricList("languages", data.languages, "Todavia no hay idiomas registrados.", (language) =>
        metricRow(language.language, language.count, "eventos con idioma", `${language.percentage}%`),
    );
    renderRecentEvents(data.recent_events);
    renderInsights(data.insights);
    renderViewsChart(data);
    renderLanguagesChart(data);
    renderTopDishesChart(data);
}

async function loadDashboard(range = activeRange) {
    const restaurantId = restaurantSelect ? restaurantSelect.value : dashboardRoot?.dataset.restaurantId;
    const params = new URLSearchParams();
    if (restaurantId) {
        params.set("restaurant_id", restaurantId);
    }
    params.set("range", range);
    const url = `/api/dashboard/summary?${params}`;

    try {
        setLoading(true);
        showState("Cargando datos reales...");
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error("Dashboard request failed");
        }
        const data = await response.json();
        setActiveRange(data.range);
        renderDashboard(data);
        showState("", false);
    } catch {
        showState("No se pudieron cargar las metricas del dashboard.", true, "error");
    } finally {
        setLoading(false);
    }
}

rangeButtons.forEach((button) => {
    button.addEventListener("click", () => {
        loadDashboard(button.dataset.rangeOption);
    });
});

refreshButton.addEventListener("click", () => {
    loadDashboard(activeRange);
});

restaurantSelect?.addEventListener("change", () => {
    dashboardRoot.dataset.restaurantId = restaurantSelect.value;
    loadDashboard(activeRange);
});

setActiveRange(activeRange);
loadDashboard(activeRange);
