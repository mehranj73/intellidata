from django import forms
from django.core.exceptions import ValidationError
from .models import Employer
from .models import EmployerError

TRANSMISSION_CHOICES=[('Connected','Connected'),
     ('Disconnected','Disconnected')
     ]

class EmployerForm(forms.ModelForm):

    employerid: forms.TextInput(attrs={'readonly':'readonly'})

    photo = forms.ImageField()

    source = forms.CharField(required=False, label='Origin', widget=forms.TextInput(attrs={'readonly':'readonly'}))

    backend_SOR_connection = forms.ChoiceField(choices=TRANSMISSION_CHOICES, widget=forms.RadioSelect, label='If connected to ODS')
    commit_indicator = forms.CharField(required=False, label='If this product data is sync-ed up with ODS', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    record_status = forms.CharField(required=False, label='If this product data got Created or Updated', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    response = forms.CharField(required=False, label='Connection response from/to ODS', widget=forms.TextInput(attrs={'readonly':'readonly'}))

    class Meta:
        model = Employer
        #exclude = ('slug','creator', 'bulk_upload_indicator')
        fields = ('employerid', 'name','description', 'FederalEmployerIdentificationNumber', 'CarrierMasterAgreementNumber', 'address_line_1', 'address_line_2', 'city', 'state', 'zipcode', 'purpose', 'photo', 'backend_SOR_connection', 'record_status', 'response')

        widgets = {
            'employerid': forms.TextInput(attrs={'readonly':'readonly'}),
            'name': forms.TextInput(attrs={'class': 'textinputclass'}),
            'description': forms.Textarea(attrs={'class': 'editable medium-editor-textarea postcontent'}),
            'FederalEmployerIdentificationNumber': forms.TextInput(attrs={'class': 'textinputclass'}),
            'CarrierMasterAgreementNumber': forms.ImageField(),
            'address_line_1': forms.TextInput(attrs={'class': 'textinputclass'}),
            'address_line_2': forms.TextInput(attrs={'class': 'textinputclass'}),
            'city': forms.TextInput(attrs={'class': 'textinputclass'}),
            'state': forms.TextInput(attrs={'class': 'textinputclass'}),
            'zipcode': forms.TextInput(attrs={'class': 'textinputclass'}),
            'purpose': forms.TextInput(attrs={'class': 'textinputclass'}),
            'photo': forms.ImageField()


        }

class EmployerErrorForm(forms.ModelForm):

    serial = forms.CharField(required=False, label='Serial#', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    name = forms.CharField(required=False, label='Employer Name', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    errorfield = forms.CharField(required=False, label='Field At Error', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    error_description = forms.CharField(required=False, label='Error description_html', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    source = forms.CharField(required=False, label='Origin', widget=forms.TextInput(attrs={'readonly':'readonly'}))
    #photo = forms.ImageField()
    #error_date = forms.DateTimeField(required=False, label='Feed Date', widget=forms.TextInput(attrs={'readonly':'readonly'}))

    class Meta:
        model = EmployerError

        #fields = ('serial', 'name', 'errorfield', 'description', 'group', 'error_date')
        exclude = ()

        widgets = {
            'creator': forms.TextInput(attrs={'readonly':'readonly'}),

        }
