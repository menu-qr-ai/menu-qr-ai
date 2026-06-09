const categoriesContainer = document.getElementById("categories")
const dishesContainer = document.getElementById("dishes")

function renderCategories() {

```
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
```

}

function renderDishes(categoryId = null) {

```
dishesContainer.innerHTML = ""

let filteredDishes = dishes

if (categoryId !== null) {

    filteredDishes = dishes.filter(dish => {
        return dish.category_id === categoryId
    })
}

filteredDishes.forEach(dish => {

    const card = document.createElement("div")

    card.className = "dish-card"

    card.innerHTML = `
        <img src="${dish.image}" class="dish-image">

        <div class="dish-content">

            <h2>${dish.name}</h2>

            <p>${dish.description}</p>

            <p><strong>Ingredients:</strong> ${dish.ingredients}</p>

            <p><strong>Allergens:</strong> ${dish.allergens}</p>

            <p class="price">${dish.price} €</p>

        </div>
    `

    dishesContainer.appendChild(card)
})
```

}

renderCategories()
renderDishes()
