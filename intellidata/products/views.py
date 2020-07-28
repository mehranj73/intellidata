from django.contrib import messages
from django.shortcuts import render
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import permission_required, login_required
from django.contrib.auth.decorators import user_passes_test
import time
from django.db.models import Q
from django.contrib.auth.mixins import(
    LoginRequiredMixin,
    PermissionRequiredMixin
)

from django.urls import reverse
from django.urls import reverse_lazy
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.views import generic
from django.db.models import Count
from groups.models import Group
from members.models import Member
from bulkuploads.models import BulkUpload
from apicodes.models import APICodes
from products.models import Product
from . import models
from . import forms
from products.forms import ProductForm
from bulkuploads.forms import BulkUploadForm
import csv
from groups.utils import BulkCreateManager
import os.path
from os import path
from django.utils.text import slugify
import misaka
import uuid

import boto3
import requests
import json

# For Rest rest_framework
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from products.serializers import ProductSerializer

class SingleProduct(LoginRequiredMixin, generic.DetailView):
    context_object_name = 'product_details'
    model = models.Product
    template_name = 'products/product_detail.html'

class ListProducts(LoginRequiredMixin, generic.ListView):
    model = models.Product
    template_name = 'products/product_list.html'

    def get_queryset(self):
        return models.Product.objects.all()
        #return models.Product.objects.get(user=request.user)


class CreateProduct(LoginRequiredMixin, PermissionRequiredMixin, generic.CreateView):
#    fields = ("name", "description")
    permission_required = 'products.add_product'
    context_object_name = 'product_details'
    redirect_field_name = 'products/product_list.html'
    form_class = forms.ProductForm
    model = models.Product
    template_name = 'products/product_form.html'

    def form_valid(self, form):
        if not self.request.user.has_perm('products.add_product'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user

            return super().form_valid(form)


#Pull from  backend system of record(SOR)
@login_required
def BackendPull(request, pk):
        # fetch the object related to passed id
        url = 'https://rr8u4gcwb3.execute-api.us-east-1.amazonaws.com/Prod/intellidataProductAPI'
        payload={'ident': pk}
        resp = requests.get(url, params=payload)
        print(resp.text)
        print(resp.status_code)
        obj = get_object_or_404(APICodes, http_response_code = resp.status_code)
        status_message=obj.http_response_message
        mesg=str(resp.status_code) + " - " + status_message
        if resp.status_code != 200:
            # This means something went wrong.
            #raise ApiError('GET /tasks/ {}'.format(resp.status_code))
            #raise APIError(resp.status_code)
            message={'messages':mesg}
            return render(request, "messages.html", context=message)
        else:
            json_data = json.loads(resp.text)

            # fetch the object related to passed id
            #obj = get_object_or_404(Product, pk = json_data["LOCAL_ID"])

            # pass the object as instance in form
            #form = ProductForm(request.POST or None, instance = obj)

            #OVERRIDE THE OBJECT WITH API data
            obj.pk = int(json_data["LOCAL_ID"])
            obj.name = json_data["NAME"]
            obj.type = json_data["TYPE"]
            obj.coverage_limit = json_data["COVERAGE_LIMIT"]
            obj.price_per_1000_units = json_data["RATE"]
            obj.product_date = json_data["CREATE_DATE"]
            obj.description = json_data["DESCRIPTION"]
            obj.description_html = misaka.html(obj.description)
            obj.photo = json_data["PHOTO"]

            context = {'product_details':obj}

            return render(request, "products/product_detail.html", context=context)


@permission_required("products.add_product")
@login_required
def VersionProduct(request, pk):
    # dictionary for initial data with
    # field names as keys
    context ={}

    # fetch the object related to passed id
    obj = get_object_or_404(Product, pk = pk)
    #obj.photo.delete()
    #obj.photo.open(mode='rb')

    # pass the object as instance in form
    form = ProductForm(request.POST or None, instance = obj)

    # save the data from the form and
    # redirect to detail_view
    if form.is_valid():
            obj.pk = int(round(time.time() * 1000))
            #form.photo = request.POST.get('photo', False)
            #form.photo = request.FILES['photo']
            form.instance.creator = request.user
            form.save()
            return HttpResponseRedirect(reverse("products:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "products/product_form.html", context)


class UpdateProduct(LoginRequiredMixin, PermissionRequiredMixin, generic.UpdateView):
    permission_required = 'products.change_product'
    context_object_name = 'product_details'
    redirect_field_name = 'products/product_detail.html'
    form_class = forms.ProductForm
    model = models.Product
    template_name = 'products/product_form.html'

    def form_valid(self, form):

        if not self.request.user.has_perm('products.change_product'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            return super().form_valid(form)



class DeleteProduct(LoginRequiredMixin, PermissionRequiredMixin, generic.DeleteView):
    permission_required = 'products.delete_product'
    context_object_name = 'product_details'
    form_class = forms.ProductForm
    model = models.Product
    template_name = 'products/product_delete_confirm.html'
    success_url = reverse_lazy("products:all")

    def form_valid(self, form):

        if not self.request.user.has_perm('products.delete_product'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            return super().form_valid(form)


@login_required
def SearchProductsForm(request):
    return render(request,'products/product_search_form.html')


class SearchProductsList(LoginRequiredMixin, generic.ListView):
    login_url = '/login/'
    model = models.Product
    template_name = 'products/product_search_list.html'

    def get_queryset(self, **kwargs): # new
        query = self.request.GET.get('q', None)
        object_list = Product.objects.filter(
            Q(pk__icontains=query) | Q(name__icontains=query) | Q(type__icontains=query) | Q(description__icontains=query)
        )
        return object_list


@permission_required("products.add_product")
@login_required
def BulkUploadProduct(request):

    context ={}

    form = BulkUploadForm(request.POST, request.FILES)

    if form.is_valid():
                form.instance.creator = request.user
                form.save()

                #s3_resource = boto3.resource('s3')
                #s3_resource.Object("intellidatastatic", "media/products.csv").download_file(f'/tmp/{"products.csv"}') # Python 3.6+
                s3 = boto3.client('s3')
                s3.download_file('intellidatastatic', 'media/products.csv', 'products.csv')
                #with open('/tmp/{"products.csv"}', 'rt') as csv_file:
                with open('products.csv', 'rt') as csv_file:
                    bulk_mgr = BulkCreateManager(chunk_size=20)
                    for row in csv.reader(csv_file):
                        bulk_mgr.add(models.Product(productid=row[0],
                                                  name=row[1],
                                                  slug=slugify(row[1]),
                                                  type=row[2],
                                                  description=row[3],
                                                  description_html = misaka.html(row[1]),
                                                  coverage_limit=row[4],
                                                  price_per_1000_units=row[5],
                                                  creator = request.user
                                                  ))
                    bulk_mgr.done()

                return HttpResponseRedirect(reverse("products:all"))
    else:
            # add form dictionary to context
            context["form"] = form

            return render(request, "bulkuploads/bulkupload_form.html", context)



@api_view(['GET', 'POST'])
def ProductList(request):

    if request.method == 'GET':
        contacts = Product.objects.all()
        serializer = ProductSerializer(contacts, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = ProductSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


#class for handling built-in API errors
class APIError(Exception):
    """An API Error Exception"""

    def __init__(self, status):
        self.status = status

    def __str__(self):
        return "APIError: status={}".format(self.status)
