"""
Stat Presets for Axiom AI Universe Creation.
This file contains predefined stat sets for various genres.
"""

STAT_PRESETS = {
    "War": [
        {"name": "Morale", "value_type": "numeric", "description": "Unit's willingness to fight", "parameters": {"min": 0, "max": 100}},
        {"name": "Logistics", "value_type": "numeric", "description": "Supply chain efficiency", "parameters": {"min": 0, "max": 100}},
        {"name": "Military Rank", "value_type": "categorical", "description": "Position in the hierarchy", "parameters": {"options": ["Conscript", "NCO", "Officer", "High Command", "Civilian"]}},
        {"name": "Entrenchment", "value_type": "numeric", "description": "Defensive preparedness", "parameters": {"min": 0, "max": 100}}
    ],
    "Fantasy": [
        {"name": "Vitality", "value_type": "numeric", "description": "Life force and physical health", "parameters": {"min": 0, "max": 1000}},
        {"name": "Mana Overload", "value_type": "numeric", "description": "Internal magical pressure", "parameters": {"min": 0, "max": 100}},
        {"name": "Archetype", "value_type": "categorical", "description": "Combat and utility role", "parameters": {"options": ["Tank", "Striker", "Caster", "Support", "Hybrid"]}},
        {"name": "Threat", "value_type": "numeric", "description": "Aggro or perceived danger level", "parameters": {"min": 0, "max": 100}}
    ],
    "Post-Apocalyptic": [
        {"name": "Infection", "value_type": "numeric", "description": "Progress of the viral or fungal strain", "parameters": {"min": 0, "max": 100}},
        {"name": "Scavenging Yield", "value_type": "numeric", "description": "Efficiency in finding resources", "parameters": {"min": 1, "max": 100}},
        {"name": "Metabolism", "value_type": "categorical", "description": "Current nutritional state", "parameters": {"options": ["Starving", "Hydrated", "Malnourished", "Well-Fed"]}},
        {"name": "Mutation Stage", "value_type": "categorical", "description": "Level of genetic alteration", "parameters": {"options": ["Pureblood", "Latent", "Active Trait", "Feral"]}}
    ],
    "Psychological Horror": [
        {"name": "Sanity", "value_type": "numeric", "description": "Grasp on objective reality", "parameters": {"min": 0, "max": 100}},
        {"name": "Paranoia Level", "value_type": "numeric", "description": "Distrust of surroundings and others", "parameters": {"min": 0, "max": 100}},
        {"name": "Coping Mechanism", "value_type": "categorical", "description": "Reflexive psychological defense", "parameters": {"options": ["Denial", "Aggression", "Flight", "Addiction"]}},
        {"name": "Guilt", "value_type": "numeric", "description": "Weight of past actions", "parameters": {"min": 0, "max": 100}}
    ],
    "Heroes Society": [
        {"name": "Public Approval", "value_type": "numeric", "description": "How the masses perceive the hero", "parameters": {"min": -100, "max": 100}},
        {"name": "Collateral Damage", "value_type": "numeric", "description": "Destruction caused during missions", "parameters": {"min": 0, "max": 1000}},
        {"name": "Power Classification", "value_type": "categorical", "description": "Nature of superhuman abilities", "parameters": {"options": ["Emitter", "Mutant", "Transformer", "Tech-Reliant"]}},
        {"name": "Burnout Risk", "value_type": "numeric", "description": "Psychological exhaustion from hero work", "parameters": {"min": 0, "max": 100}}
    ],
    "Virtual Reality": [
        {"name": "Sync Rate", "value_type": "numeric", "description": "Connection quality between mind and avatar", "parameters": {"min": 0, "max": 100}},
        {"name": "Glitch Corruption", "value_type": "numeric", "description": "Digital instability and code decay", "parameters": {"min": 0, "max": 100}},
        {"name": "Access Privilege", "value_type": "categorical", "description": "User clearance within the system", "parameters": {"options": ["Guest", "Standard User", "Moderator", "Admin", "Rogue AI"]}},
        {"name": "System Load", "value_type": "numeric", "description": "Hardware strain from complex scripts", "parameters": {"min": 0, "max": 100}}
    ],
    "Steampunk": [
        {"name": "Boiler Pressure", "value_type": "numeric", "description": "Steam power intensity", "parameters": {"min": 0, "max": 100}},
        {"name": "Soot Toxicity", "value_type": "numeric", "description": "Lung pollution and grime buildup", "parameters": {"min": 0, "max": 100}},
        {"name": "Social Class", "value_type": "categorical", "description": "Victorian-era societal standing", "parameters": {"options": ["Aristocrat", "Bourgeois", "Factory Worker", "Scrapper"]}},
        {"name": "Augmentation Load", "value_type": "numeric", "description": "Strain from mechanical implants", "parameters": {"min": 0, "max": 10}}
    ],
    "Sport": [
        {"name": "Momentum", "value_type": "numeric", "description": "Psychological flow and performance peak", "parameters": {"min": 0, "max": 100}},
        {"name": "Stamina", "value_type": "numeric", "description": "Physical endurance for the match", "parameters": {"min": 0, "max": 100}},
        {"name": "Team Role", "value_type": "categorical", "description": "Tactical function in the team", "parameters": {"options": ["Playmaker", "Finisher", "Defender", "Support", "Captain"]}},
        {"name": "Clutch Factor", "value_type": "numeric", "description": "Performance under high pressure", "parameters": {"min": 1, "max": 20}}
    ],
    "Mech": [
        {"name": "Hull Integrity", "value_type": "numeric", "description": "Structural health of the machine", "parameters": {"min": 0, "max": 100}},
        {"name": "Heat Level", "value_type": "numeric", "description": "Internal reactor temperature", "parameters": {"min": 0, "max": 100}},
        {"name": "Neural Sync", "value_type": "numeric", "description": "Interface efficiency with the pilot", "parameters": {"min": 0, "max": 100}},
        {"name": "Chassis Class", "value_type": "categorical", "description": "Weight category of the Mech", "parameters": {"options": ["Light", "Medium", "Heavy", "Superheavy"]}}
    ],
    "Politics": [
        {"name": "Political Capital", "value_type": "numeric", "description": "Influence and favor currency", "parameters": {"min": 0, "max": 100}},
        {"name": "Scandal Exposure", "value_type": "numeric", "description": "Risk of public disgrace", "parameters": {"min": 0, "max": 100}},
        {"name": "Alignment", "value_type": "categorical", "description": "Ideological positioning", "parameters": {"options": ["Reactionary", "Conservative", "Centrist", "Progressive", "Radical"]}},
        {"name": "Lobby Influence", "value_type": "numeric", "description": "Pressure from special interest groups", "parameters": {"min": 0, "max": 100}}
    ],
    "Western": [
        {"name": "Grit", "value_type": "numeric", "description": "Toughness and resolve in the wild", "parameters": {"min": 0, "max": 100}},
        {"name": "Bounty", "value_type": "numeric", "description": "Price on the head", "parameters": {"min": 0, "max": 10000}},
        {"name": "Reputation", "value_type": "categorical", "description": "Notoriety level in the frontier", "parameters": {"options": ["Greenhorn", "Lawman", "Outlaw", "Legend", "Pariah"]}},
        {"name": "Draw Speed", "value_type": "numeric", "description": "Quickness on the trigger", "parameters": {"min": 1, "max": 100}}
    ],
    "Slice of Life": [
        {"name": "Stress Capacity", "value_type": "numeric", "description": "Daily resilience to pressure", "parameters": {"min": 0, "max": 100}},
        {"name": "Social Battery", "value_type": "numeric", "description": "Energy for interpersonal interaction", "parameters": {"min": 0, "max": 100}},
        {"name": "Obligations", "value_type": "numeric", "description": "Number of active daily chores/duties", "parameters": {"min": 0, "max": 10}},
        {"name": "Life Stage", "value_type": "categorical", "description": "Current era of personal growth", "parameters": {"options": ["Student", "Early Career", "Established", "Midlife", "Retired"]}}
    ],
    "Crime": [
        {"name": "Heat", "value_type": "numeric", "description": "Law enforcement attention level", "parameters": {"min": 0, "max": 100}},
        {"name": "Alibi Strength", "value_type": "numeric", "description": "Credibility of the current cover story", "parameters": {"min": 0, "max": 100}},
        {"name": "Underworld Ties", "value_type": "numeric", "description": "Connections to organized crime", "parameters": {"min": 0, "max": 100}},
        {"name": "Role", "value_type": "categorical", "description": "Position within the crew or case", "parameters": {"options": ["Mastermind", "Enforcer", "Informant", "Detective", "Bystander"]}}
    ],
    "Cosmic Horror": [
        {"name": "Eldritch Insight", "value_type": "numeric", "description": "Understanding of the forbidden truth", "parameters": {"min": 0, "max": 100}},
        {"name": "Dread Accumulation", "value_type": "numeric", "description": "Total weight of cosmic despair", "parameters": {"min": 0, "max": 100}},
        {"name": "Cult Affiliation", "value_type": "categorical", "description": "Connection to forbidden sects", "parameters": {"options": ["Unaware", "Investigator", "Touched", "Initiate", "Vessel"]}},
        {"name": "Cosmic Insignificance", "value_type": "numeric", "description": "Realization of one's own smallness", "parameters": {"min": 0, "max": 100}}
    ],
    "Romance": [
        {"name": "Chemistry", "value_type": "numeric", "description": "Dynamic spark between characters", "parameters": {"min": 0, "max": 100}},
        {"name": "Red Flags", "value_type": "numeric", "description": "Warning signs of toxic behavior", "parameters": {"min": 0, "max": 10}},
        {"name": "Attachment Style", "value_type": "categorical", "description": "How the character bonds", "parameters": {"options": ["Secure", "Anxious", "Avoidant", "Disorganized"]}},
        {"name": "Drama Escalation", "value_type": "numeric", "description": "Intensity of relational conflict", "parameters": {"min": 0, "max": 100}}
    ],
    "Paranormal": [
        {"name": "Veil Thickness", "value_type": "numeric", "description": "Barrier between physical and spirit world", "parameters": {"min": 0, "max": 100}},
        {"name": "EMF", "value_type": "numeric", "description": "Electro-magnetic interference levels", "parameters": {"min": 0, "max": 100}},
        {"name": "Entity Classification", "value_type": "categorical", "description": "Type of supernatural presence", "parameters": {"options": ["Poltergeist", "Demon", "Residual", "Shadow", "Revenant"]}},
        {"name": "Possession Risk", "value_type": "numeric", "description": "Vulnerability to spectral takeover", "parameters": {"min": 0, "max": 100}}
    ],
    "Goofy Ahh": [
        {"name": "Brainrot", "value_type": "numeric", "description": "Exposure to surreal internet culture", "parameters": {"min": 0, "max": 100}},
        {"name": "Aura", "value_type": "numeric", "description": "Immeasurable vibe check score", "parameters": {"min": -1000, "max": 1000}},
        {"name": "Meme Status", "value_type": "categorical", "description": "Societal archetype in the cringe-verse", "parameters": {"options": ["Based", "Cringe", "Sigma", "NPC", "Schizo"]}},
        {"name": "Plot Armor", "value_type": "numeric", "description": "Luck protection against logic", "parameters": {"min": 0, "max": 100}}
    ],
    "Sci-Fi": [
        {"name": "Life Support", "value_type": "numeric", "description": "Oxygen and environmental stability", "parameters": {"min": 0, "max": 100}},
        {"name": "Shield Harmonics", "value_type": "numeric", "description": "Energy barrier frequency alignment", "parameters": {"min": 0, "max": 100}},
        {"name": "Origin", "value_type": "categorical", "description": "Place of birth or manufacturing", "parameters": {"options": ["Terran", "Belter", "Synthetic", "Hive-Mind", "Uplifted"]}},
        {"name": "System Override", "value_type": "numeric", "description": "Efficiency in hacking foreign tech", "parameters": {"min": 0, "max": 100}}
    ],
    "Abstract": [
        {"name": "Reality Cohesion", "value_type": "numeric", "description": "Stability of the local dimension", "parameters": {"min": 0, "max": 100}},
        {"name": "Abstract Logic", "value_type": "numeric", "description": "Power of metaphorical reasoning", "parameters": {"min": 0, "max": 100}},
        {"name": "Concept Form", "value_type": "categorical", "description": "Current manifestation of thought", "parameters": {"options": ["Geometric", "Fluid", "Non-Euclidean", "Static Noise"]}},
        {"name": "Cognitive Dissonance", "value_type": "numeric", "description": "Conflict between perception and being", "parameters": {"min": 0, "max": 100}}
    ],
    "Medieval": [
        {"name": "Vassal Loyalty", "value_type": "numeric", "description": "Faithfulness of subjects", "parameters": {"min": 0, "max": 100}},
        {"name": "Plague Risk", "value_type": "numeric", "description": "Vulnerability to black death", "parameters": {"min": 0, "max": 100}},
        {"name": "Estate", "value_type": "categorical", "description": "Feudal social standing", "parameters": {"options": ["Landless", "Baron", "Count", "Duke", "Monarch"]}},
        {"name": "Piety", "value_type": "numeric", "description": "Devotion to the church", "parameters": {"min": -100, "max": 100}}
    ],
    "Dark Fantasy": [
        {"name": "Corruption", "value_type": "numeric", "description": "Shadow's influence on the soul", "parameters": {"min": 0, "max": 100}},
        {"name": "Flickering Hope", "value_type": "numeric", "description": "Resistance to total despair", "parameters": {"min": 0, "max": 100}},
        {"name": "Sacrifice Cost", "value_type": "numeric", "description": "Weight of blood magic price", "parameters": {"min": 1, "max": 50}},
        {"name": "Doom Stage", "value_type": "categorical", "description": "Severity of the character's curse", "parameters": {"options": ["Untouched", "Marked", "Tainted", "Condemned", "Lost"]}}
    ]
}
