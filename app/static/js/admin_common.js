// Shared helpers for the owner/manager management screens (Carta, Mesas y QR...).
(() => {
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

    function readBootstrap(id) {
        const node = document.getElementById(id);
        return node ? JSON.parse(node.textContent || "{}") : null;
    }

    function createAlert(alertBox) {
        let timer = null;
        return (message, tone = "success") => {
            clearTimeout(timer);
            alertBox.textContent = message;
            alertBox.dataset.tone = tone;
            alertBox.hidden = false;
            timer = setTimeout(() => {
                alertBox.hidden = true;
            }, tone === "error" ? 7000 : 3500);
        };
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

    // JSON requests relative to a base path, with CSRF via HostAISecurity.
    function createRequester(basePath) {
        return async (path, options = {}) => {
            const response = await window.HostAISecurity.fetch(`${basePath}${path}`, {
                headers: {"Content-Type": "application/json", Accept: "application/json"},
                ...options,
            });
            if (!response.ok) {
                throw new Error(await errorMessage(response));
            }
            return response.status === 204 ? null : response.json();
        };
    }

    // Serialises mutations: one at a time, then reload, then report.
    function createActionRunner({reload, showAlert}) {
        let busy = false;
        const run = async (action, successMessage) => {
            if (busy) {
                return false;
            }
            busy = true;
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
                busy = false;
                document.body.classList.remove("is-busy");
            }
        };
        run.isBusy = () => busy;
        return run;
    }

    const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

    window.HostAIAdmin = Object.freeze({
        el,
        readBootstrap,
        createAlert,
        createRequester,
        createActionRunner,
        plural,
    });
})();
