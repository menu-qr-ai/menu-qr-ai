const categoriesContainer = document.getElementById("categories")
const dishesContainer = document.getElementById("dishes")

function renderCategories() {

    categoriesContainer.innerHTML = ""

    categories.forEach(category => {

        const button = document.createElement("button")

        button.className = "category-button"

        button.innerText = category.name

        button.onclick = () => {
            renderDishes(category.id)
        }

        categoriesContainer.appendChild(button)
    })
}

function renderDishes(categoryId) {

    dishesContainer.innerHTML = ""

    const filtered = dishes.filter(
        dish => dish.category_id === categoryId
    )

    filtered.forEach(dish => {

        const card = document.createElement("div")

        card.className = "dish-card"

        card.innerHTML = `
            <img
                src="${dish.image}"
                class="dish-image"
            >

            <div class="dish-content">

                <h2>${dish.name}</h2>

                <p>${dish.description}</p>

                <p>
                    <strong>Ingredients:</strong>
                    ${dish.ingredients}
                </p>

                <p>
                    <strong>Allergens:</strong>
                    ${dish.allergens}
                </p>

                <div class="dish-footer">

                    <span class="price">
                        €${dish.price}
                    </span>

                    <button
                        class="translate-button"
                        onclick="translateDish(${dish.id})"
                    >
                        Translate
                    </button>

                </div>

            </div>
        `

        dishesContainer.appendChild(card)
    })
}

async function translateDish(dishId) {

    const lang = prompt(
        "Language? (en, fr, de, it)"
    )

    if (!lang) return

    const response = await fetch(
        `/ai/translate-dish/${dishId}?lang=${lang}`
    )

    const data = await response.json()

    alert(
        `${data.name}\n\n${data.description}`
    )
}

renderCategories()

if (categories.length > 0) {
    renderDishes(categories[0].id)
}