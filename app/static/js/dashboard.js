const dashboardRoot = document.querySelector(".dashboard-shell");
const dashboardState = document.getElementById("dashboardState");

function numberFormat(value) {
    return new Intl.NumberFormat("es-ES").format(Number(value || 0));
}

function showState(message, visible = true) {
    dashboardState.textContent = message;
    dashboardState.classList.toggle("is-visible", visible);
}

function setKpis(summary) {
    Object.entries(summary).forEach(([key, value]) => {
        const node = document.querySelector(`[data-kpi="${key}"]`);
        if (node) {
            node.textContent = numberFormat(value);
        }
    });
}

function emptyRow(message) {
    const element = document.createElement("div");
    element.className = "empty-row";
    element.textContent = message;
    return element;
}

function metricRow(label, value, detail = "") {
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

    const valueNode = document.createElement("strong");
    valueNode.className = "metric-value";
    valueNode.textContent = numberFormat(value);

    row.append(copy, valueNode);
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
        ].filter(Boolean).join(" · ") || "Evento general";
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

function prepareCharts(data) {
    window.dashboardChartData = {
        languages: data.languages,
        topDishes: data.top_dishes,
        topSearches: data.top_searches,
    };
}

function renderDashboard(data) {
    setKpis(data.summary);
    renderMetricList("topDishes", data.top_dishes, "Todavia no hay platos vistos.", (dish) =>
        metricRow(dish.name, dish.views, dish.dish_id ? `ID ${dish.dish_id}` : "Sin plato asociado"),
    );
    renderMetricList("topSearches", data.top_searches, "Todavia no hay busquedas.", (search) =>
        metricRow(search.query, search.count, "busqueda registrada"),
    );
    renderMetricList("languages", data.languages, "Todavia no hay idiomas registrados.", (language) =>
        metricRow(language.language, language.count, "eventos con idioma"),
    );
    renderRecentEvents(data.recent_events);
    renderInsights(data.insights);
    prepareCharts(data);
}

async function loadDashboard() {
    const restaurantId = dashboardRoot?.dataset.restaurantId;
    const params = new URLSearchParams();
    if (restaurantId) {
        params.set("restaurant_id", restaurantId);
    }
    const url = `/api/dashboard/summary${params.toString() ? `?${params}` : ""}`;

    try {
        showState("Cargando datos reales...");
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error("Dashboard request failed");
        }
        const data = await response.json();
        renderDashboard(data);
        showState("", false);
    } catch {
        showState("No se pudieron cargar las metricas del dashboard.");
    }
}

loadDashboard();
