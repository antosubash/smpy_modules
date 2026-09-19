"""US-flavoured value pools for the demo-data seeder.

Inline literals only — no ``faker`` or any other new dependency (see the
package docstring in ``__init__.py``). Every pool here is deliberately small
and boring: it exists to make generated records *read* like a small US
business's data, not to be exhaustive.

Every list below carries ``# fmt: skip``: left to itself, ``ruff format``
explodes a list literal to one element per line, which would blow every pool
here well past the 300-line cap for no readability gain over the packed rows
already used.
"""

from __future__ import annotations

#: (code, name) for the 50 US states — no territories, so every value here
#: is also a legal ``ship_state``/``state`` choice.
US_STATES: list[tuple[str, str]] = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"),
]  # fmt: skip

#: (city, state code) pairs — picked together so a generated address is at
#: least internally consistent, ~60 entries across every region.
CITIES: list[tuple[str, str]] = [
    ("Birmingham", "AL"), ("Huntsville", "AL"), ("Anchorage", "AK"),
    ("Phoenix", "AZ"), ("Tucson", "AZ"), ("Little Rock", "AR"),
    ("Los Angeles", "CA"), ("San Diego", "CA"), ("San Francisco", "CA"),
    ("Sacramento", "CA"), ("Oakland", "CA"), ("Denver", "CO"), ("Boulder", "CO"),
    ("Hartford", "CT"), ("Wilmington", "DE"), ("Miami", "FL"), ("Orlando", "FL"),
    ("Tampa", "FL"), ("Jacksonville", "FL"), ("Atlanta", "GA"), ("Savannah", "GA"),
    ("Honolulu", "HI"), ("Boise", "ID"), ("Chicago", "IL"), ("Springfield", "IL"),
    ("Indianapolis", "IN"), ("Des Moines", "IA"), ("Wichita", "KS"),
    ("Louisville", "KY"), ("New Orleans", "LA"), ("Baton Rouge", "LA"),
    ("Portland", "ME"), ("Baltimore", "MD"), ("Boston", "MA"), ("Cambridge", "MA"),
    ("Detroit", "MI"), ("Grand Rapids", "MI"), ("Minneapolis", "MN"), ("St. Paul", "MN"),
    ("Jackson", "MS"), ("Kansas City", "MO"), ("St. Louis", "MO"), ("Billings", "MT"),
    ("Omaha", "NE"), ("Las Vegas", "NV"), ("Reno", "NV"), ("Manchester", "NH"),
    ("Newark", "NJ"), ("Jersey City", "NJ"), ("Albuquerque", "NM"),
    ("New York", "NY"), ("Buffalo", "NY"), ("Rochester", "NY"),
    ("Charlotte", "NC"), ("Raleigh", "NC"), ("Fargo", "ND"), ("Columbus", "OH"),
    ("Cleveland", "OH"), ("Cincinnati", "OH"), ("Oklahoma City", "OK"), ("Tulsa", "OK"),
    ("Portland", "OR"), ("Eugene", "OR"), ("Philadelphia", "PA"), ("Pittsburgh", "PA"),
    ("Providence", "RI"), ("Charleston", "SC"), ("Columbia", "SC"), ("Sioux Falls", "SD"),
    ("Nashville", "TN"), ("Memphis", "TN"), ("Austin", "TX"), ("Dallas", "TX"),
    ("Houston", "TX"), ("San Antonio", "TX"), ("Salt Lake City", "UT"),
    ("Burlington", "VT"), ("Richmond", "VA"), ("Arlington", "VA"),
    ("Seattle", "WA"), ("Spokane", "WA"), ("Charleston", "WV"),
    ("Milwaukee", "WI"), ("Madison", "WI"), ("Cheyenne", "WY"),
]  # fmt: skip

FIRST_NAMES: list[str] = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
    "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
    "Matthew", "Margaret", "Anthony", "Sandra", "Mark", "Ashley", "Donald", "Kimberly",
    "Steven", "Emily", "Andrew", "Donna", "Paul", "Michelle", "Joshua", "Amanda",
    "Kenneth", "Melissa", "Kevin", "Rebecca", "Brian", "Laura", "George", "Stephanie",
    "Edward", "Dorothy", "Ronald", "Amy", "Timothy", "Angela", "Jason", "Brenda",
    "Jeffrey", "Emma", "Ryan", "Olivia", "Jacob", "Sophia", "Gary", "Nicole",
    "Nicholas", "Christina", "Eric", "Samantha", "Jonathan", "Katherine", "Stephen", "Victoria",
]  # fmt: skip

LAST_NAMES: list[str] = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker",
    "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales", "Murphy",
]  # fmt: skip

STREET_NAMES: list[str] = [
    "Main", "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake",
    "Hill", "Walnut", "Park", "Sunset", "Highland", "Ridge", "Willow", "Meadow",
    "Prairie", "Birch", "Chestnut", "Spruce", "River", "Harbor", "Franklin", "Jefferson",
    "Lincoln", "Madison", "Monroe", "Church", "School", "Union", "Broadway", "Market",
    "Orchard", "Forest", "Valley", "Spring", "Summit", "Cherry", "College", "Depot",
]  # fmt: skip

STREET_SUFFIXES: list[str] = [
    "St", "Ave", "Blvd", "Ln", "Dr", "Rd", "Way", "Ct", "Ter", "Pl",
]  # fmt: skip

COMPANY_PREFIXES: list[str] = [
    "Blue Ridge", "Silverline", "Cascade", "Northgate", "Ironwood", "Bright Path",
    "Summit", "Crestview", "Lonestar", "Golden Gate", "Liberty", "Union",
    "Sterling", "Vertex", "Highland", "Meadowbrook", "Riverbend", "Pinnacle",
    "Cedar Grove", "Redwood", "Harbor", "Prairie", "Anchor", "Beacon",
    "Frontier", "Timberline", "Copperfield", "Falcon", "Granite", "Maple Leaf",
    "Bluestone", "Wildwood", "Fairview", "Clearwater", "Eastgate", "Westfield",
]  # fmt: skip

COMPANY_WORDS: list[str] = [
    "Technologies", "Solutions", "Logistics", "Manufacturing", "Holdings", "Partners",
    "Industries", "Group", "Enterprises", "Systems", "Consulting", "Ventures",
    "Foods", "Energy", "Media", "Robotics", "Analytics", "Freight",
]  # fmt: skip

COMPANY_LEGAL_SUFFIXES: list[str] = ["Inc.", "LLC", "Corp.", "Co.", "Ltd.", "Group"]  # fmt: skip

INDUSTRY_BLURBS: list[str] = [
    "logistics and freight", "enterprise software", "renewable energy", "consumer goods",
    "industrial manufacturing", "financial services", "healthcare technology",
    "digital marketing", "food and beverage", "specialty retail", "biotechnology",
    "construction and engineering",
]  # fmt: skip

JOB_TITLES: list[str] = [
    "Sales Manager", "VP of Operations", "Marketing Director", "Software Engineer",
    "Account Executive", "Customer Success Manager", "Product Manager", "Financial Analyst",
    "HR Coordinator", "Operations Analyst", "Business Development Manager", "Data Scientist",
    "Support Specialist", "Procurement Manager", "Logistics Coordinator", "Regional Director",
    "Executive Assistant", "Quality Assurance Lead", "Supply Chain Manager",
    "Chief Technology Officer",
]  # fmt: skip

EMAIL_DOMAINS: list[str] = [
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "icloud.com", "aol.com", "protonmail.com", "live.com",
]  # fmt: skip

PRODUCT_CATEGORIES: list[str] = [
    "Electronics", "Home & Garden", "Sporting Goods", "Office Supplies", "Apparel",
    "Toys & Games", "Automotive", "Health & Beauty", "Grocery", "Pet Supplies",
    "Tools & Hardware", "Books & Media",
]  # fmt: skip

PRODUCT_ADJECTIVES: list[str] = [
    "Ultra", "Pro", "Compact", "Deluxe", "Portable", "Classic", "Rugged", "Smart",
    "Ergonomic", "Heavy-Duty", "Wireless", "Adjustable", "Premium", "Essential",
    "Modular", "All-Weather", "Lightweight", "Insulated",
]  # fmt: skip

PRODUCT_NOUNS: list[str] = [
    "Office Chair", "Desk Lamp", "Backpack", "Water Bottle", "Coffee Maker",
    "Bluetooth Speaker", "Running Shoes", "Yoga Mat", "Tool Kit", "Garden Hose",
    "Cutting Board", "Storage Bin", "Phone Case", "Bike Helmet", "Camping Tent",
    "Sleeping Bag", "Dog Leash", "Cat Tree", "Notebook", "Stapler",
    "Monitor Stand", "Keyboard", "Blender", "Air Fryer", "Toolbox",
]  # fmt: skip

TAG_POOL: list[str] = [
    "sale", "new-arrival", "bestseller", "clearance", "limited-edition", "eco-friendly",
    "premium", "refurbished", "staff-pick", "seasonal", "exclusive", "trending",
]  # fmt: skip

ORDER_STATUSES: list[str] = ["pending", "paid", "shipped", "delivered", "cancelled"]  # fmt: skip
ORDER_STATUS_WEIGHTS: list[float] = [0.10, 0.20, 0.20, 0.40, 0.10]
