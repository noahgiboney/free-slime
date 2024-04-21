from fastapi import APIRouter, Depends
from enum import Enum
from pydantic import BaseModel
from src.api import auth
import sqlalchemy
from src import database as db
from fastapi import HTTPException
import random

router = APIRouter(
    prefix="/bottler",
    tags=["bottler"],
    dependencies=[Depends(auth.get_api_key)],
)

class PotionInventory(BaseModel):
    potion_type: list[int]
    quantity: int

def generate_potion_name():
    adjectives = ["Magic", "Ancient", "Mystic", "Rare", "Invisible", "Fiery", "Icy", "Glowing", "Dark", "Shimmering"]
    nouns = ["Elixir", "Potion", "Brew", "Serum", "Tonic", "Mixture", "Drink", "Concoction", "Blend", "Solution"]
    extras = ["of Power", "of Stealth", "of Healing", "of Energy", "of Luck", "", "", "", "", ""]  # Including some blanks for variability

    # Choose a random adjective and noun
    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    extra = random.choice(extras)

    # Form the potion name and strip any trailing spaces if no extra word is added
    potion_name = f"{adjective} {noun} {extra}".strip()
    return potion_name

def generate_sku(name):
    return name.upper().replace(" ", "_")

@router.post("/deliver/{order_id}")
def post_deliver_bottles(potions_delivered: list[PotionInventory], order_id: int):
    print(f"DEBUG POTIONS DELIVERED: {potions_delivered}")

    with db.engine.begin() as connection:
        for potion in potions_delivered:
            green, red, blue, dark = potion.potion_type
            potion_quantity = potion.quantity

            # Check if the potion already exists based on RGBD values
            sql_check_potion = """
                SELECT id, quantity FROM potions
                WHERE green = :green AND red = :red AND blue = :blue AND dark = :dark
            """
            result = connection.execute(sqlalchemy.text(sql_check_potion), {
                'green': green,
                'red': red,
                'blue': blue,
                'dark': dark
            })
            potion_result = result.mappings().first()  # Use .mappings() and .first() to access as a dict

            if potion_result:
                # Potion exists, update the quantity
                new_quantity = potion_result['quantity'] + potion_quantity
                sql_update_potion = """
                    UPDATE potions
                    SET quantity = :new_quantity
                    WHERE id = :id
                """
                connection.execute(sqlalchemy.text(sql_update_potion), {
                    'new_quantity': new_quantity,
                    'id': potion_result['id']
                })
            else:
                # Potion does not exist, create a new record
                name = generate_potion_name()
                sku = generate_sku(name)
                sql_insert_potion = """
                    INSERT INTO potions (green, red, blue, dark, name, sku, price, quantity)
                    VALUES (:green, :red, :blue, :dark, :name, :sku, :price, :quantity)
                """
                connection.execute(sqlalchemy.text(sql_insert_potion), {
                    'green': green,
                    'red': red,
                    'blue': blue,
                    'dark': dark,
                    'name': name,
                    'sku': sku,
                    'price': 30,  # Assuming a fixed price, modify as necessary
                    'quantity': potion_quantity
                })
            
            # Update ml in the global inventory for each color component
            for color, amount in zip(['green', 'red', 'blue', 'dark'], [green, red, blue, dark]):
                ml_update = amount * potion_quantity
                sql_update_ml = f"""
                    UPDATE global_inventory 
                    SET num_{color}_ml = num_{color}_ml - :ml_update
                    WHERE num_{color}_ml >= :ml_update
                """
                result = connection.execute(sqlalchemy.text(sql_update_ml), {'ml_update': ml_update})
                if result.rowcount == 0:
                    connection.rollback()  # Rollback if any update fails
                    raise HTTPException(status_code=400, detail=f"Not enough {color} ml available to fulfill the order.")

    print(f"Potions delivered: {potions_delivered}, Order ID: {order_id}")
    return {"status": "success", "message": "Delivery processed successfully"}

def generate_recepies(inventory, num_recipes=10):
    total_inventory = sum(inventory)
    if total_inventory == 0:
        return []  
    
    recipes = []
    while len(recipes) < num_recipes:
        parts = [random.randint(0, stock) for stock in inventory]
        total_parts = sum(parts)
        if total_parts == 0:
            continue  

        normalized_parts = [part * 100 // total_parts for part in parts]
        adjustment = 100 - sum(normalized_parts)
        for i in range(len(normalized_parts)):
            if normalized_parts[i] > 0:
                normalized_parts[i] += adjustment
                break

        recipes.append(tuple(normalized_parts))

    return recipes

@router.post("/plan")
def get_bottle_plan():
    # fetch potion ml from inventory
    with db.engine.begin() as connection:
        sql = "SELECT num_green_ml, num_red_ml, num_blue_ml, num_dark_ml FROM global_inventory"
        result = connection.execute(sqlalchemy.text(sql))
        inventory_data = result.fetchone()

    inventory = list(inventory_data)

    # generate 10 possible receipies
    recipes = generate_recepies(inventory, 10) 

    bottle_plan = []
    
    #calculate bottles based on recipies
    for recipe in recipes:
        max_bottles = float('inf')
        for i, ratio in enumerate(recipe):
            if ratio > 0:
                required_amount = ratio 
                max_bottles = min(max_bottles, inventory[i] // required_amount)
        
        if max_bottles > 0:
            bottle_plan.append({"potion_type": recipe, "quantity": max_bottles})
            for i, ratio in enumerate(recipe):
                inventory[i] -= max_bottles * ratio

    print(f"DEBUG: BOTTLE PLAN: {bottle_plan}")
    return bottle_plan

if __name__ == "__main__":
    print(get_bottle_plan())