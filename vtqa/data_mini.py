"""A small synthetic company database with template-made questions (works offline).

Why it exists: it lets you test the whole pipeline in minutes, with a real model or the mock.
Every question comes with the gold SQL, and the gold answer is computed by running that SQL,
so the answers are correct by construction. It is a SANITY benchmark, not a research benchmark:
use WikiTableQuestions (data_wikitq.py) for the numbers you report.
"""
from __future__ import annotations

import random
from collections import defaultdict

import pandas as pd

from .db import load_tables, safe_execute
from .scoring import rows_to_answer
from .types import Example

NAMES = [
    "Ayesha Khan", "Bilal Ahmed", "Chaudhry Imran", "Daniyal Malik", "Eman Fatima", "Farhan Siddiqui",
    "Gul Rukh", "Hamza Iqbal", "Iqra Noor", "Junaid Akram", "Kiran Shah", "Laiba Zahid",
    "Mustafa Raza", "Nimra Yousaf", "Omar Farooq", "Pari Gul", "Qasim Ali", "Rabia Sheikh",
    "Saad Hussain", "Tania Mirza", "Usman Ghani", "Vania Aslam", "Waqar Butt", "Zainab Tariq",
]
DEPTS = [("Engineering", "Lahore"), ("Marketing", "Karachi"), ("Finance", "Islamabad"),
         ("Support", "Faisalabad"), ("Research", "Multan")]
ROLES = ["Engineer", "Analyst", "Manager", "Technician"]
PRODUCTS = ["Laptop", "Phone", "Tablet", "Monitor", "Router"]
REGIONS = ["North", "South", "East", "West"]
YEARS = [2021, 2022, 2023, 2024]


def build_tables(seed: int = 7) -> dict:
    rng = random.Random(seed)
    departments = pd.DataFrame(
        [{"dept_id": i + 1, "dept_name": n, "city": c, "budget": rng.randrange(200, 901, 50) * 1000}
         for i, (n, c) in enumerate(DEPTS)]
    )
    salaries = set()
    emp_rows = []
    for i, name in enumerate(NAMES):
        dept_id = (i % len(DEPTS)) + 1 if i < 15 else rng.randrange(1, len(DEPTS) + 1)
        while True:
            salary = rng.randrange(40000, 150001, 500)
            if salary not in salaries:
                salaries.add(salary)
                break
        emp_rows.append({"emp_id": i + 1, "name": name, "dept_id": dept_id, "role": rng.choice(ROLES),
                         "salary": salary, "hire_year": rng.randrange(2012, 2025)})
    employees = pd.DataFrame(emp_rows)
    sales = pd.DataFrame(
        [{"sale_id": i + 1, "emp_id": rng.randrange(1, len(NAMES) + 1), "product": rng.choice(PRODUCTS),
          "amount": rng.randrange(200, 5001, 10), "year": rng.choice(YEARS), "region": rng.choice(REGIONS)}
         for i in range(60)]
    )
    return {"departments": departments, "employees": employees, "sales": sales}


def _candidates():
    """(template, question, gold_sql, difficulty, optional tie-check sql)."""
    c = []
    emp_dept = "FROM employees e JOIN departments d ON e.dept_id = d.dept_id"
    for d, _ in DEPTS:
        c.append(("count_in_dept", f"How many employees work in the {d} department?",
                  f"SELECT COUNT(*) {emp_dept} WHERE d.dept_name = '{d}'", "easy", None))
        c.append(("dept_city", f"In which city is the {d} department located?",
                  f"SELECT city FROM departments WHERE dept_name = '{d}'", "easy", None))
        c.append(("avg_salary_dept", f"What is the average salary in the {d} department?",
                  f"SELECT AVG(e.salary) {emp_dept} WHERE d.dept_name = '{d}'", "medium", None))
        c.append(("top_salary_dept", f"Who has the highest salary in the {d} department?",
                  f"SELECT e.name {emp_dept} WHERE d.dept_name = '{d}' ORDER BY e.salary DESC LIMIT 1", "medium",
                  f"SELECT e.salary {emp_dept} WHERE d.dept_name = '{d}' ORDER BY e.salary DESC LIMIT 2"))
    for n in NAMES:
        c.append(("salary_of", f"What is the salary of {n}?",
                  f"SELECT salary FROM employees WHERE name = '{n}'", "easy", None))
        c.append(("sales_count_person", f"How many sales did {n} make?",
                  f"SELECT COUNT(*) FROM sales s JOIN employees e ON s.emp_id = e.emp_id WHERE e.name = '{n}'",
                  "medium", None))
    for y in [2014, 2016, 2018, 2020, 2022]:
        c.append(("hired_after", f"Which employees were hired after {y}?",
                  f"SELECT name FROM employees WHERE hire_year > {y}", "easy", None))
    for x in [60000, 80000, 100000, 120000]:
        c.append(("earn_more_than", f"List the names of employees who earn more than {x}.",
                  f"SELECT name FROM employees WHERE salary > {x}", "medium", None))
    for r in REGIONS:
        for y in YEARS:
            c.append(("total_sales_region_year", f"What is the total sales amount in the {r} region in {y}?",
                      f"SELECT SUM(amount) FROM sales WHERE region = '{r}' AND year = {y}", "medium", None))
    for word, order in (("highest", "DESC"), ("lowest", "ASC")):
        c.append(("dept_total_salary", f"Which department has the {word} total salary?",
                  f"SELECT d.dept_name {emp_dept} GROUP BY d.dept_id ORDER BY SUM(e.salary) {order} LIMIT 1", "hard",
                  f"SELECT SUM(salary) AS s FROM employees GROUP BY dept_id ORDER BY s {order} LIMIT 2"))
    for y in YEARS:
        c.append(("largest_sale_year", f"Who made the largest single sale in {y}?",
                  f"SELECT e.name FROM sales s JOIN employees e ON s.emp_id = e.emp_id WHERE s.year = {y} "
                  f"ORDER BY s.amount DESC LIMIT 1", "hard",
                  f"SELECT amount FROM sales WHERE year = {y} ORDER BY amount DESC LIMIT 2"))
        c.append(("top_product_year", f"Which product has the highest total sales amount in {y}?",
                  f"SELECT product FROM sales WHERE year = {y} GROUP BY product ORDER BY SUM(amount) DESC LIMIT 1",
                  "hard",
                  f"SELECT SUM(amount) AS s FROM sales WHERE year = {y} GROUP BY product ORDER BY s DESC LIMIT 2"))
    c.append(("above_dept_avg", "How many employees earn more than the average salary of their own department?",
              "SELECT COUNT(*) FROM employees e WHERE e.salary > "
              "(SELECT AVG(salary) FROM employees WHERE dept_id = e.dept_id)", "hard", None))
    for k in (2, 3, 4):
        c.append(("dept_more_than_k", f"How many departments have more than {k} employees?",
                  f"SELECT COUNT(*) FROM (SELECT dept_id FROM employees GROUP BY dept_id HAVING COUNT(*) > {k})",
                  "hard", None))
    return c


def load_mini(n: int = 60, seed: int = 7) -> list:
    tables = build_tables(seed=7)  # the database is always the same; `seed` only picks questions
    conn = load_tables(tables)
    rng = random.Random(seed)
    by_template = defaultdict(list)
    for template, q, sql, diff, check in _candidates():
        res = safe_execute(conn, sql)
        if not res.ok or not res.rows:
            continue
        if template == "sales_count_person" and res.rows[0][0] == 0:
            continue
        if template == "hired_after" and not (1 <= len(res.rows) <= 12):
            continue
        if template == "earn_more_than" and not (2 <= len(res.rows) <= 10):
            continue
        if template == "dept_more_than_k" and res.rows[0][0] == 0:
            continue
        if check:  # superlatives must have a unique winner
            chk = safe_execute(conn, check)
            if chk.ok and len(chk.rows) >= 2 and chk.rows[0][0] == chk.rows[1][0]:
                continue
        by_template[template].append((q, sql, diff, rows_to_answer(res.rows)))
    for items in by_template.values():
        rng.shuffle(items)
    order = sorted(by_template)
    rng.shuffle(order)
    picked, r = [], 0
    while len(picked) < n and any(r < len(by_template[t]) for t in order):
        for t in order:
            if r < len(by_template[t]) and len(picked) < n:
                picked.append(by_template[t][r])
        r += 1
    return [
        Example(id=f"mini-{i + 1:03d}", question=q, tables=tables, gold_answer=ans, table_key="mini",
                gold_sql=sql, difficulty=diff)
        for i, (q, sql, diff, ans) in enumerate(picked)
    ]
