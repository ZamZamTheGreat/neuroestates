from flask import Flask, render_template

app = Flask(__name__)

# Example data - update with your actual agency info
AGENCIES = [
    {
        "name": "NeuroEdge Properties",
        "location": "Windhoek",
        "tagline": "Smart Real Estate Solutions",
        "url": "http://127.0.0.1:5090/"
    },
    {
        "name": "Ramos Estates",
        "location": "Swakopmund",
        "tagline": "Your Coastal Home Partner",
        "url": "http://127.0.0.1:5091/"
    },
    {
        "name": "Windhoek Property Brokers",
        "location": "Windhoek",
        "tagline": "Integrity in Every Deal",
        "url": "http://127.0.0.1:5092/"
    },
]

@app.route('/')
def home():
    return render_template('index.html', agencies=AGENCIES)

if __name__ == '__main__':
    app.run(port=7000, debug=True)
