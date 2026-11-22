"""Formularios de la app de tienda."""

from django import forms
from django.core.validators import RegexValidator


class DireccionEntregaForm(forms.Form):
    """Dirección de entrega del checkout, capturada por campos.

    Se pide por partes para que el cliente no olvide datos (colonia, código
    postal) y para validar cada uno. El pedido sigue guardando un solo texto en
    `Pedido.direccion_entrega` (ver `como_texto()`), así no hace falta migrar la
    base y los pedidos anteriores se leen igual en el admin.
    """

    calle = forms.CharField(label='Calle', max_length=150)
    numero_exterior = forms.CharField(label='Número exterior', max_length=20)
    numero_interior = forms.CharField(label='Número interior', max_length=20, required=False)
    colonia = forms.CharField(label='Colonia', max_length=100)
    codigo_postal = forms.CharField(
        label='Código postal',
        max_length=5,
        validators=[RegexValidator(r'^\d{5}$', 'El código postal debe tener 5 dígitos.')],
    )
    ciudad = forms.CharField(label='Ciudad o alcaldía', max_length=100)
    estado = forms.CharField(label='Estado', max_length=100)
    referencias = forms.CharField(
        label='Referencias', max_length=500, required=False, widget=forms.Textarea
    )

    def como_texto(self) -> str:
        """Une los campos en el formato postal de México, sin las partes opcionales vacías.

        Las referencias se dejan en una sola línea para que el texto se lea
        completo en el admin y en la confirmación del pedido. Solo se puede
        llamar después de `is_valid()`.
        """
        datos = self.cleaned_data
        partes = [f"{datos['calle']} {datos['numero_exterior']}"]
        if datos['numero_interior']:
            partes.append(f"int. {datos['numero_interior']}")
        partes += [
            f"col. {datos['colonia']}",
            f"C.P. {datos['codigo_postal']}",
            datos['ciudad'],
            datos['estado'],
        ]
        texto = ', '.join(partes)
        referencias = ' '.join(datos['referencias'].split())
        if referencias:
            texto += f'. Referencias: {referencias}'
        return texto
