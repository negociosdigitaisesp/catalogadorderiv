import glob

for f in glob.glob('*.sql'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    content = content.replace('n_30d >= 20', 'n_30d >= 4')
    content = content.replace('n_30d >= 15', 'n_30d >= 3')
    content = content.replace('n_7d >= 4', 'n_7d >= 2')
    content = content.replace('n_7d >= 3', 'n_7d >= 1')
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
