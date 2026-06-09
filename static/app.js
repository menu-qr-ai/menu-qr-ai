```javascript id="x4n32s"
const categoriesContainer =
    document.getElementById("categories")

const dishesContainer =
    document.getElementById("dishes")


function renderCategories() {

    categoriesContainer.innerHTML = ""

    const allButton =
        document.createElement("button")

    allButton.innerText = "All"

    allButton.className =
        "category-button"

    allButton.onclick = () => {
        renderDishes()
    }

    categoriesContainer.appendChild(
        allButton
    )

    categories.forEach(category => {

        const button =
            document.createElement("button")

        button.innerText =
            category.name

        button.className =
            "category-button"

        button.onclick = () => {
            renderDishes(category.id)
        }

        categoriesContainer.appendChild(
            button
        )

    })

}


function renderDishes(categoryId = null) {

    dishesContainer.innerHTML = ""

    let filteredDishes = dishes

    if (categoryId !== null) {

        filteredDishes =
            dishes.filter(dish =>
                dish.category_id === categoryId
            )

    }

    filteredDishes.forEach(dish => {

        const card =
            document.createElement("div")

        card.className =
            "dish-card"

        card.innerHTML = `
            <img
                src="${dish.image}"
                class="dish-image"
            >

            <div class="dish-content">

                <h2 class="dish-title">
                    ${dish.name}
                </h2>

                <p class="dish-description">
                    ${dish.description}
                </p>

                <div class="dish-price">
                    €${dish.price}
                </div>

                <div class="dish-meta">
                    <strong>Ingredients:</strong>
                    ${dish.ingredients}
                </div>

                <div class="dish-meta">
                    <strong>Allergens:</strong>
                    ${dish.allergens}
                </div>

                <button
                    class="translate-button"
                    onclick="translateDish(${dish.id})"
                >
                    Translate with AI
                </button>

            </div>
        `

        dishesContainer.appendChild(card)

    })

}


async function translateDish(dishId) {

    const lang =
        prompt("Language? Example: en, fr, de")

    if (!lang) {
        return
    }

    try {

        const response = await fetch(
            `/ai/translate-dish/${dishId}?lang=${lang}`
        )

        const data = await response.json()

        if (data.error) {

            alert(data.error)

            return

        }

        alert(
            `Translated:\n\n` +
            `${data.name}\n\n` +
            `${data.description}`
        )

    }

    catch (error) {

        console.error(error)

        alert("Translation error")

    }

}


renderCategories()

renderDishes()
```
