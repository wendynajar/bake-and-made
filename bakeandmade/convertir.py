p = 'catalogo.json'
b = open(p, 'rb').read()
try:
    b.decode('utf-8')
    print('Ya era UTF-8')
except UnicodeDecodeError:
    open(p, 'w', encoding='utf-8', newline='').write(b.decode('cp1252'))
    print('Convertido de 1252 a UTF-8')
