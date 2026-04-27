import os
import sys

# Setup django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
django.setup()

from menu.models import Category, MenuItem

def seed_menu():
    # Define categories
    categories_data = [
        "Hot Beverages",
        "Cold Beverages",
        "Breakfast",
        "Desserts",
        "Snacks"
    ]

    # Map created categories for easy assignment
    categories = {}
    for name in categories_data:
        cat, created = Category.objects.get_or_create(name=name)
        categories[name] = cat
        print(f"Created category: {name}")

    # Define menu items
    menu_items_data = [
        # Hot Beverages
        {"name": "Espresso", "category": "Hot Beverages", "price": 150.00, "description": "Classic single shot espresso."},
        {"name": "Americano", "category": "Hot Beverages", "price": 180.00, "description": "Espresso with hot water."},
        {"name": "Cappuccino", "category": "Hot Beverages", "price": 220.00, "description": "Espresso with steamed milk and thick foam."},
        {"name": "Cafe Latte", "category": "Hot Beverages", "price": 220.00, "description": "Espresso with steamed milk and a light layer of foam."},
        {"name": "Hot Chocolate", "category": "Hot Beverages", "price": 250.00, "description": "Rich and creamy hot chocolate."},
        
        # Cold Beverages
        {"name": "Iced Americano", "category": "Cold Beverages", "price": 200.00, "description": "Chilled espresso over ice."},
        {"name": "Iced Cafe Latte", "category": "Cold Beverages", "price": 250.00, "description": "Chilled espresso, milk, and ice."},
        {"name": "Frappuccino", "category": "Cold Beverages", "price": 300.00, "description": "Blended iced coffee with whipped cream."},
        {"name": "Lemon Iced Tea", "category": "Cold Beverages", "price": 180.00, "description": "Refreshing black tea infused with fresh lemon."},
        {"name": "Mango Smoothie", "category": "Cold Beverages", "price": 350.00, "description": "Freshly blended mangoes with milk and yogurt."},

        # Breakfast
        {"name": "Avocado Toast", "category": "Breakfast", "price": 450.00, "description": "Smashed avocado on toasted sourdough with poached egg."},
        {"name": "Pancakes", "category": "Breakfast", "price": 380.00, "description": "Fluffy pancakes served with maple syrup and butter."},
        {"name": "English Breakfast", "category": "Breakfast", "price": 550.00, "description": "Eggs, bacon, sausages, baked beans, and toast."},

        # Desserts
        {"name": "Cheesecake", "category": "Desserts", "price": 400.00, "description": "New York style baked cheesecake."},
        {"name": "Chocolate Brownie", "category": "Desserts", "price": 250.00, "description": "Warm chocolate brownie perfect with coffee."},
        {"name": "Tiramisu", "category": "Desserts", "price": 450.00, "description": "Classic Italian coffee-flavored dessert."},

        # Snacks
        {"name": "French Fries", "category": "Snacks", "price": 200.00, "description": "Crispy golden french fries."},
        {"name": "Chicken Nuggets", "category": "Snacks", "price": 300.00, "description": "Crispy battered chicken bites."},
        {"name": "Margarita Pizza", "category": "Snacks", "price": 550.00, "description": "Classic pizza with tomato sauce, mozzarella, and basil."}
    ]

    # Create menu items
    for item_data in menu_items_data:
        category = categories[item_data.pop("category")]
        item, created = MenuItem.objects.get_or_create(
            name=item_data["name"],
            category=category,
            defaults={
                "price": item_data["price"],
                "description": item_data["description"]
            }
        )
        if created:
            print(f"Created menu item: {item.name}")
        else:
            print(f"Menu item already exists: {item.name}")

    print("Successfully seeded the database with categories and menu items.")

if __name__ == "__main__":
    seed_menu()
