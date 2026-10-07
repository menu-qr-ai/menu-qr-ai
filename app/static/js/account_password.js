(() => {
    const form = document.getElementById("passwordForm");
    const alertBox = document.getElementById("passwordAlert");
    const success = document.getElementById("passwordSuccess");
    const submit = document.getElementById("passwordSubmit");
    if (!form) {
        return;
    }

    const showError = (message) => {
        alertBox.textContent = message;
        alertBox.hidden = false;
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        alertBox.hidden = true;
        const fields = form.elements;
        const current = fields.current_password.value;
        const next = fields.new_password.value;
        if (!current || !next) {
            showError("Rellena la contraseña actual y la nueva.");
            return;
        }
        if (next.length < 10) {
            showError("La contraseña nueva necesita al menos 10 caracteres.");
            return;
        }
        if (next !== fields.confirm_password.value) {
            showError("Las dos contraseñas nuevas no coinciden.");
            return;
        }
        submit.disabled = true;
        try {
            const response = await window.HostAISecurity.fetch("/api/auth/password", {
                method: "POST",
                headers: {"Content-Type": "application/json", Accept: "application/json"},
                body: JSON.stringify({current_password: current, new_password: next}),
            });
            if (!response.ok) {
                const payload = await response.json().catch(() => ({}));
                showError(
                    payload?.error?.message
                    || payload?.detail?.[0]?.msg
                    || "No se pudo cambiar la contraseña. Inténtalo de nuevo.",
                );
                return;
            }
            form.reset();
            form.hidden = true;
            success.hidden = false;
        } catch (error) {
            showError("No hay conexión. Inténtalo de nuevo.");
        } finally {
            submit.disabled = false;
        }
    });
})();
