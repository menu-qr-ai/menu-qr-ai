(() => {
    const unsafeMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

    const csrfToken = () => document.querySelector(
        'meta[name="csrf-token"]',
    )?.content || "";

    const safeNextPath = () => {
        const value = `${window.location.pathname}${window.location.search}`;
        return value.startsWith("/") && !value.startsWith("//")
            ? value
            : "/app";
    };

    const secureFetch = async (input, options = {}) => {
        const request = input instanceof Request ? input : null;
        const url = new URL(request?.url || input, window.location.href);
        const method = String(
            options.method || request?.method || "GET",
        ).toUpperCase();
        const headers = new Headers(
            options.headers || request?.headers || {},
        );

        if (
            url.origin === window.location.origin
            && unsafeMethods.has(method)
        ) {
            const token = csrfToken();
            if (token) {
                headers.set("X-CSRF-Token", token);
            }
        }

        const response = await window.fetch(input, {
            credentials: "same-origin",
            ...options,
            headers,
        });
        if (
            response.status === 401
            && window.location.pathname !== "/login"
        ) {
            const next = encodeURIComponent(safeNextPath());
            window.location.assign(`/login?next=${next}`);
            return response;
        }
        if (response.status === 403) {
            response.clone().json().then((payload) => {
                const code = payload?.error?.code;
                if (
                    code === "csrf_token_missing"
                    || code === "csrf_token_invalid"
                ) {
                    window.dispatchEvent(new CustomEvent(
                        "hostai:csrf-error",
                        {detail: payload.error},
                    ));
                }
            }).catch(() => {});
        }
        return response;
    };

    window.HostAISecurity = Object.freeze({
        csrfToken,
        fetch: secureFetch,
    });
})();
