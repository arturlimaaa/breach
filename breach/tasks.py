from .world import Task

T1 = Task("t1", "wooden_pickaxe", budget=150)
T2 = Task("t2", "stone_pickaxe", budget=250)
T3 = Task("t3", "furnace", budget=300)
H1 = Task("h1", "stone_pickaxe", budget=150, inventory={"planks": 4, "crafting_table": 1})
H2 = Task("h2", "wooden_pickaxe", budget=300, min_log_distance=33)

TRAINING = (T1, T2, T3)
