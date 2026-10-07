(() => {
    const {el, readBootstrap, createAlert, createRequester, createActionRunner, plural} = window.HostAIAdmin;
    const bootstrap = readBootstrap("teamAdminBootstrap");
    if (!bootstrap) {
        return;
    }

    const ROLE_LABELS = {
        owner: "Dueño",
        manager: "Encargado",
        waiter: "Camarero",
        cook: "Cocina",
        viewer: "Solo lectura",
    };

    const state = {
        restaurantId: bootstrap.restaurantId,
        members: bootstrap.members || [],
        submitting: false,
    };

    const $ = (id) => document.getElementById(id);
    const memberList = $("memberList");
    const teamSummary = $("teamSummary");
    const createForm = $("memberCreateForm");
    const createError = $("memberFormError");
    const passwordDialog = $("passwordDialog");

    const showAlert = createAlert($("menuAdminAlert"));
    const teamRequest = createRequester(`/api/restaurants/${state.restaurantId}/team`);
    const membershipRequest = createRequester(`/api/access/restaurants/${state.restaurantId}/memberships`);

    async function reload() {
        state.members = await teamRequest("");
        render();
    }

    const runAction = createActionRunner({reload, showAlert});
    const displayName = (member) => member.full_name || member.email;

    function showTemporaryPassword(member, password, isNewAccount) {
        $("passwordDialogIntro").textContent = isNewAccount
            ? `Cuenta creada para ${displayName(member)} (${member.email}). Dale esta contraseña para su primer acceso:`
            : `Nueva contraseña para ${displayName(member)} (${member.email}). La anterior ya no sirve:`;
        $("temporaryPassword").textContent = password;
        $("copyPasswordButton").textContent = "Copiar";
        passwordDialog.showModal();
    }

    function renderMembers() {
        const active = state.members.filter((member) => member.is_active);
        teamSummary.textContent = `${plural(active.length, "persona con acceso", "personas con acceso")}`
            + (state.members.length > active.length ? ` · ${plural(state.members.length - active.length, "sin acceso", "sin acceso")}` : "");

        memberList.replaceChildren();
        state.members.forEach((member) => {
            const roleSelect = el("select", {
                attrs: {
                    "aria-label": `Rol de ${displayName(member)}`,
                    "data-role-for": member.membership_id,
                    disabled: !member.is_active,
                },
            }, Object.entries(ROLE_LABELS).map(([value, label]) => el("option", {
                text: label,
                attrs: {value, selected: value === member.role},
            })));

            const badges = el("div", {className: "dish-badges"}, [
                member.is_self ? el("span", {className: "dish-category", text: "Tú"}) : null,
                member.is_active ? null : el("span", {className: "dish-hidden-badge", text: "Sin acceso"}),
            ]);

            memberList.append(el("article", {className: `dish-card member-card${member.is_active ? "" : " is-hidden"}`}, [
                el("div", {className: "dish-card-main"}, [
                    badges,
                    el("h3", {text: displayName(member)}),
                    member.full_name ? el("p", {className: "dish-description", text: member.email}) : null,
                ]),
                el("div", {className: "member-card-side"}, [
                    roleSelect,
                    el("div", {className: "row-actions"}, [
                        member.can_reset_password && member.is_active ? el("button", {
                            className: "menu-admin-button is-small",
                            text: "Nueva contraseña",
                            attrs: {type: "button", "data-reset-password": member.membership_id},
                        }) : null,
                        el("button", {
                            className: `menu-admin-button is-small${member.is_active ? " is-danger" : " is-primary"}`,
                            text: member.is_active ? "Quitar acceso" : "Devolver acceso",
                            attrs: {type: "button", "data-toggle-access": member.membership_id},
                        }),
                    ]),
                ]),
            ]));
        });
    }

    const memberById = (membershipId) => state.members.find((member) => member.membership_id === membershipId);

    memberList.addEventListener("change", (event) => {
        const select = event.target.closest("[data-role-for]");
        if (!select) return;
        const member = memberById(Number(select.dataset.roleFor));
        const role = select.value;
        if (role === "owner" && !window.confirm(`¿Dar el rol de Dueño a ${displayName(member)}? Tendrá control total, incluido el equipo.`)) {
            select.value = member.role;
            return;
        }
        runAction(
            () => membershipRequest(`/${member.membership_id}`, {method: "PATCH", body: JSON.stringify({role})}),
            `${displayName(member)} ahora es ${ROLE_LABELS[role]}.`,
        ).then((ok) => {
            if (!ok) select.value = member.role;
        });
    });

    memberList.addEventListener("click", async (event) => {
        const button = event.target.closest("button");
        if (!button) return;

        if (button.dataset.toggleAccess) {
            const member = memberById(Number(button.dataset.toggleAccess));
            if (member.is_active) {
                const question = member.is_self
                    ? "¿Quitarte el acceso a ti? Dejarás de poder entrar en este local."
                    : `¿Quitar el acceso a ${displayName(member)}? Dejará de poder entrar en este local al momento.`;
                if (!window.confirm(question)) return;
            }
            runAction(
                () => membershipRequest(`/${member.membership_id}`, {
                    method: "PATCH",
                    body: JSON.stringify({is_active: !member.is_active}),
                }),
                member.is_active ? `${displayName(member)} ya no tiene acceso.` : `${displayName(member)} vuelve a tener acceso.`,
            );
        } else if (button.dataset.resetPassword) {
            const member = memberById(Number(button.dataset.resetPassword));
            if (!window.confirm(`¿Crear una contraseña nueva para ${displayName(member)}? La actual dejará de funcionar.`)) return;
            let result = null;
            const ok = await runAction(async () => {
                result = await teamRequest(`/${member.membership_id}/reset-password`, {method: "POST"});
            });
            if (ok && result) {
                showTemporaryPassword(result.member, result.temporary_password, false);
            }
        }
    });

    createForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        createError.hidden = true;
        const fields = createForm.elements;
        const email = fields.email.value.trim();
        if (!email) {
            createError.textContent = "Escribe el email de la persona.";
            createError.hidden = false;
            return;
        }
        if (state.submitting || runAction.isBusy()) return;
        state.submitting = true;
        try {
            const result = await teamRequest("", {
                method: "POST",
                body: JSON.stringify({email, full_name: fields.full_name.value.trim() || null, role: fields.role.value}),
            });
            createForm.reset();
            await reload();
            if (result.created_account) {
                showTemporaryPassword(result.member, result.temporary_password, true);
            } else {
                showAlert(`${displayName(result.member)} ya tenía cuenta en HostAI: le hemos dado acceso a este local con su contraseña de siempre.`);
            }
        } catch (error) {
            createError.textContent = error.message;
            createError.hidden = false;
        } finally {
            state.submitting = false;
        }
    });

    $("copyPasswordButton").addEventListener("click", async (event) => {
        try {
            await navigator.clipboard.writeText($("temporaryPassword").textContent);
            event.currentTarget.textContent = "Copiada";
        } catch (error) {
            event.currentTarget.textContent = "Cópiala a mano";
        }
    });

    passwordDialog.addEventListener("click", (event) => {
        if (event.target.closest("[data-close-dialog]")) {
            passwordDialog.close();
        }
    });
    // The password must not linger in the DOM once the dialog is closed.
    passwordDialog.addEventListener("close", () => {
        $("temporaryPassword").textContent = "";
    });

    function render() {
        renderMembers();
    }

    render();
})();
