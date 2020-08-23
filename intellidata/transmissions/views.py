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
from employers.models import Employer
from employees.models import Employee
from django.contrib.auth.models import User
from bulkuploads.models import BulkUpload
from apicodes.models import APICodes
from transmissions.models import Transmission
from transmissions.models import TransmissionError
from transmissions.models import TransmissionErrorAggregate
from . import models
from . import forms
from transmissions.forms import TransmissionForm
from bulkuploads.forms import BulkUploadForm
import csv
from employers.utils import BulkCreateManager
from employers.utils import ApiDomains
import os.path
from os import path
from django.utils.text import slugify
import misaka
import uuid
from django.shortcuts import get_object_or_404

import boto3
import requests
import json
import re
from botocore.exceptions import NoCredentialsError
import io
from django.db.models import Count


# For Rest rest_framework
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from transmissions.serializers import TransmissionSerializer

class SingleTransmission(LoginRequiredMixin, generic.DetailView):
    context_object_name = 'transmission_details'
    model = models.Transmission
    template_name = 'transmissions/transmission_detail.html'

class ListTransmissions(LoginRequiredMixin, generic.ListView):
    model = models.Transmission
    template_name = 'transmissions/transmission_list.html'

    def get_queryset(self):
        return models.Transmission.objects.all()
        #return models.transmission.objects.get(user=request.user)


class CreateTransmission(LoginRequiredMixin, PermissionRequiredMixin, generic.CreateView):
#    fields = ("name", "description")
    permission_required = 'transmissions.add_transmission'
    context_object_name = 'transmission_details'
    redirect_field_name = 'transmissions/transmission_list.html'
    form_class = forms.TransmissionForm
    model = models.Transmission
    template_name = 'transmissions/transmission_form.html'

    def form_valid(self, form):
        if not self.request.user.has_perm('transmissions.add_transmission'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            form.instance.record_status = "Created"
            form.instance.source = "Web App"

            return super().form_valid(form)


#Pull from  backend system of record(SOR)
@permission_required("transmissions.add_transmission")
@login_required
def BackendPull(request, pk):
        # fetch the object related to passed id
        #url = 'https://94q78vev60.execute-api.us-east-1.amazonaws.com/Prod/intellidataTransmissionAPI/latest'

        prod_obj = get_object_or_404(Transmission, pk = pk)

        api = ApiDomains()
        url = api.transmission + "/" + "latest"
        payload={'ident': prod_obj.transmissionid}
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
            #obj = get_object_or_404(Transmission, pk = json_data["LOCAL_ID"])

            # pass the object as instance in form
            #form = TransmissionForm(request.POST or None, instance = obj)

            #OVERRIDE THE OBJECT WITH API data
            obj.pk = int(json_data["LOCAL_ID"])
            obj.transmissionid = json_data["TRANSMISSION_ID"]
            obj.SenderName = json_data["SENDER_NAME"]
            obj.BenefitAdministratorPlatform = json_data["BENEFIT_ADMINISTRATOR_PLATFORM"]
            obj.ReceiverName = json_data["RECEIVER_NAME"]

            obj.TestProductionCode = json_data["TEST_PRODUCTION_CODE"]
            obj.TransmissionTypeCode = json_data["TRANSMISSION_TYPE_CODE"]
            obj.SystemVersionIdentifier = json_data["SYSTEM_VERSION_IDENTIFIER"]
            obj.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            #obj.crerator = get_object_or_404(User, pk=obj.creatorid)
            obj.create_date = json_data["CREATE_DATE"]
            obj.backend_SOR_connection = json_data["CONNECTION"]
            obj.response = json_data["RESPONSE"]
            obj.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj.record_status = json_data["RECORD_STATUS"]

            context = {'transmission_details':obj}

            return render(request, "transmissions/transmission_detail.html", context=context)



#Pull from  backend system of record(SOR)
@permission_required("transmissions.add_transmission")
@login_required
def ListTransmissionsHistory(request, pk):

                context ={}

                prod_obj = get_object_or_404(Transmission, pk = pk)

                api = ApiDomains()
                url = api.transmission + "/" + "history"
                #url = 'https://94q78vev60.execute-api.us-east-1.amazonaws.com/Prod/intellidatatransmissionAPI/history'
                payload={'ident': prod_obj.transmissionid}

                resp = requests.get(url, params=payload)
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
                    json_data=[]
                    dict_data=[]
                    obj_data=[]
                    json_data = resp.json()

                    #print(json_data[0])
                    #print(json_data[1])
                    for ix in range(len(json_data)):
                     obj = Transmission()
                      #dict_data.append(json.loads(json_data[ix]))
                     obj.pk = int(json_data[ix]["LOCAL_ID"])
                     obj.transmissionid = json_data[ix]["TRANSMISSION_ID"]
                     obj.SenderName = json_data[ix]["SENDER_NAME"]
                     obj.BenefitAdministratorPlatform = json_data[ix]["BENEFIT_ADMINISTRATOR_PLATFORM"]
                     obj.ReceiverName = json_data[ix]["RECEIVER_NAME"]

                     obj.TestProductionCode = json_data[ix]["TEST_PRODUCTION_CODE"]
                     obj.TransmissionTypeCode = json_data[ix]["TRANSMISSION_TYPE_CODE"]
                     obj.SystemVersionIdentifier = json_data[ix]["SYSTEM_VERSION_IDENTIFIER"]
                     #obj.photo = json_data[ix]["PHOTO"]
                     obj.creator = User.objects.get(pk=int(json_data[ix]["CREATOR"]))
                     obj.create_date = json_data[ix]["CREATE_DATE"]
                     obj.backend_SOR_connection = json_data[ix]["CONNECTION"]
                     obj.response = json_data[ix]["RESPONSE"]
                     obj.record_status = json_data[ix]["RECORD_STATUS"]
                     obj.commit_indicator = json_data[ix]["COMMIT_INDICATOR"]

                     obj_data.append(obj)

                    context = {'object_list':obj_data}

                    return render(request, "transmissions/transmission_list.html", context=context)

                    #mesg_obj = get_object_or_404(APICodes, http_response_code = 1000)
                    #status_message=mesg_obj.http_response_message
                    #mesg="1000" + " - " + status_message
                    # add form dictionary to context
                    #message={'messages':mesg}
                    #return render(request, "messages.html", context=message)


@permission_required("transmissions.add_transmission")
@login_required
def RefreshTransmission(request, pk):
        # fetch the object related to passed id
        context ={}
        prod_obj = get_object_or_404(Transmission, pk = pk)

        api = ApiDomains()
        url = api.transmission + "/" + "refresh"
        #url = 'https://94q78vev60.execute-api.us-east-1.amazonaws.com/Prod/intellidatatransmissionAPI/history'
        payload={'ident': prod_obj.transmissionid}

        resp = requests.get(url, params=payload)
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
            json_data=[]

            json_data = resp.json()
            obj1=Transmission()

            #OVERRIDE THE OBJECT WITH API data
            obj1.pk = int(json_data["LOCAL_ID"])
            obj1.transmissionid = json_data["TRANSMISSION_ID"]
            obj1.SenderName = json_data["SENDER_NAME"]
            obj1.BenefitAdministratorPlatform = json_data["BENEFIT_ADMINISTRATOR_PLATFORM"]
            obj1.ReceiverName = json_data["RECEIVER_NAME"]

            obj1.TestProductionCode = json_data["TEST_PRODUCTION_CODE"]
            obj1.TransmissionTypeCode = json_data["TRANSMISSION_TYPE_CODE"]
            obj1.SystemVersionIdentifier = json_data["SYSTEM_VERSION_IDENTIFIER"]

            obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            #obj.crerator = get_object_or_404(User, pk=obj.creatorid)
            obj1.create_date = json_data["CREATE_DATE"]
            obj1.backend_SOR_connection = "Disconnected"
            obj1.response = json_data["RESPONSE"]
            obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj1.record_status = json_data["RECORD_STATUS"]

            obj1.save()

            context = {'transmission_details':obj1}

            return render(request, "transmissions/transmission_detail.html", context=context)


@permission_required("transmissions.add_transmission")
@login_required
def VersionTransmission(request, pk):
    # dictionary for initial data with
    # field names as keys
    context ={}

    # fetch the object related to passed id
    obj = get_object_or_404(Transmission, pk = pk)
    #obj.photo.delete()
    #obj.photo.open(mode='rb')

    # pass the object as instance in form
    form = TransmissionForm(request.POST or None, instance = obj)

    # save the data from the form and
    # redirect to detail_view
    if form.is_valid():
            obj.pk = int(round(time.time() * 1000))
            #form.photo = request.POST.get('photo', False)
            #form.photo = request.FILES['photo']
            form.instance.creator = request.user
            form.instance.record_status = "Created"
            form.save()
            return HttpResponseRedirect(reverse("transmissions:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "transmissions/transmission_form.html", context)


class UpdateTransmission(LoginRequiredMixin, PermissionRequiredMixin, generic.UpdateView):
    permission_required = 'transmissions.change_transmission'
    context_object_name = 'transmission_details'
    redirect_field_name = 'transmissions/transmission_detail.html'
    form_class = forms.TransmissionForm
    model = models.Transmission
    template_name = 'transmissions/transmission_form.html'

    def form_valid(self, form):

        if not self.request.user.has_perm('transmissions.change_transmission'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            form.instance.record_status = "Updated"
            return super().form_valid(form)


class DeleteTransmission(LoginRequiredMixin, PermissionRequiredMixin, generic.DeleteView):
    permission_required = 'transmissions.delete_transmission'
    context_object_name = 'transmission_details'
    form_class = forms.TransmissionForm
    model = models.Transmission
    template_name = 'transmissions/transmission_delete_confirm.html'
    success_url = reverse_lazy("transmissions:all")

    def form_valid(self, form):
        print("hello")
        if not self.request.user.has_perm('transmissions.delete_transmission'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            return super().form_valid(form)


@login_required
def SearchTransmissionsForm(request):
    return render(request,'transmissions/transmission_search_form.html')


class SearchTransmissionsList(LoginRequiredMixin, generic.ListView):
    login_url = '/login/'
    model = models.Transmission
    template_name = 'transmissions/transmission_search_list.html'

    def get_queryset(self, **kwargs): # new
        query = self.request.GET.get('q', None)
        object_list = Transmission.objects.filter(
            Q(transmissionid__icontains=query) | Q(SenderName__icontains=query) | Q(BenefitAdministratorPlatform__icontains=query) | Q(ReceiverName__icontains=query) | Q(TestProductionCode__icontains=query) | Q(TransmissionTypeCode__icontains=query)
        )

        #change start for remote SearchTransmissionsForm
        if not object_list:
            api = ApiDomains()
            url = api.transmission + "/" + "refresh"
            #url = 'https://94q78vev60.execute-api.us-east-1.amazonaws.com/Prod/intellidataTransmissionAPI/history'
            payload={'ident': query}

            resp = requests.get(url, params=payload)
            print(resp.status_code)

            obj = get_object_or_404(APICodes, http_response_code = resp.status_code)
            status_message=obj.http_response_message
            mesg=str(resp.status_code) + " - " + status_message

            if resp.status_code != 200:
                # This means something went wrong.
                #raise ApiError('GET /tasks/ {}'.format(resp.status_code))
                #raise APIError(resp.status_code)
                #message={'messages':mesg}
                #return render(self.request, "messages.html", context=message)
                print("Status Code: " + str(resp.status_code))
            else:
                json_data=[]

                json_data = resp.json()
                obj_data=[]
                obj1=Transmission()

                #OVERRIDE THE OBJECT WITH API data
                obj1.pk = int(json_data["LOCAL_ID"])
                obj1.transmissionid = json_data["TRANSMISSION_ID"]
                obj1.SenderName = json_data["SENDER_NAME"]
                obj1.BenefitAdministratorPlatform = json_data["BENEFIT_ADMINISTRATOR_PLATFORM"]
                obj1.ReceiverName = json_data["RECEIVER_NAME"]

                obj1.TestProductionCode = json_data["TEST_PRODUCTION_CODE"]
                obj1.TransmissionTypeCode = json_data["TRANSMISSION_TYPE_CODE"]
                obj1.SystemVersionIdentifier = json_data["SYSTEM_VERSION_IDENTIFIER"]

                obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
                #obj.crerator = get_object_or_404(User, pk=obj.creatorid)
                obj1.create_date = json_data["CREATE_DATE"]
                obj1.backend_SOR_connection = "Disconnected"
                obj1.response = "Pulled From Backend"
                obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
                obj1.record_status = json_data["RECORD_STATUS"]

                obj1.save()



                #obj_data.append(obj1)
                #print(obj_data)

                #context = {'object_list':obj_data}

                #return render(self.request, "TransmissionTransmissions/Transmission_search_list.html", context=context)
                object_remote_list = Transmission.objects.filter(transmissionid=query)
                print(object_remote_list)
                return object_remote_list

        else:
        #change end for remote SearchtransmissionsForm

            return object_list


class ShowEmployersList(LoginRequiredMixin, generic.ListView):
    model = Transmission
    template_name = 'employers/employer_list.html'

    def get_queryset(self): # new
        transmission = get_object_or_404(models.Transmission, pk=self.kwargs['pk'])
        object_list = transmission.employer_set.all()

        return object_list


@permission_required("transmissions.add_transmission")
@login_required
def BulkUploadTransmission(request):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.client('s3')
                    s3.download_file('intellidatastatic', 'media/transmissions.csv', 'transmissions.csv')

                    with open('transmissions.csv', 'rt') as csv_file:
                        array_good =[]
                        array_bad = []
                        #array_bad =[]
                        for row in csv.reader(csv_file):
                                                      bad_ind = 0
                                                      array1=[]
                                                      array2=[]

                                                      #populate serial number
                                                      serial=row[0]
                                                      array2.append(serial)

                                                    #pass Transmission:
                                                      transmissionid=row[1]
                                                      array2.append(transmissionid)
                                                       #validate name
                                                      SenderName=row[2]
                                                      if SenderName == "":
                                                          bad_ind = 1
                                                          description = "Sender Name is mandatory"
                                                          array1.append(serial)
                                                          array1.append(transmissionid)
                                                          array1.append(SenderName)
                                                          array1.append(SenderName)
                                                          array1.append(description)
                                                          array_bad.append(array1)

                                                      else:
                                                          array2.append(SenderName)

                                                      BenefitAdministratorPlatform=row[3]
                                                      array2.append(BenefitAdministratorPlatform)

                                                      ReceiverName=row[4]
                                                      array2.append(ReceiverName)

                                                      TestProductionCode=row[6]
                                                      array2.append(TestProductionCode)

                                                      TransmissionTypeCode=row[7]
                                                      array2.append(TransmissionTypeCode)

                                                      SystemVersionIdentifier=row[8]
                                                      array2.append(SystemVersionIdentifier)

                                                      if bad_ind == 0:
                                                          array_good.append(array2)



                        # create good file
                    #with open('Transmissions1.csv', 'w', newline='') as clean_file:
                    ##    writer = csv.writer(clean_file)
                    #    writer.writerows(array_good)

                    buff1 = io.StringIO()

                    writer = csv.writer(buff1, dialect='excel', delimiter=',')
                    writer.writerows(array_good)

                    buff2 = io.BytesIO(buff1.getvalue().encode())

                        # check if a version of the good file already exists
                #    try:
                #        s3.Object('my-bucket', 'dootdoot.jpg').load()
                #    except botocore.exceptions.ClientError as e:
                #        if e.response['Error']['Code'] == "404":
                #            # The object does not exist.
                #            ...
                #        else:
                #            # Something else has gone wrong.
                #            raise
                #    else:
                #        # do something

# create good file
                    try:
                        response = s3.delete_object(Bucket='intellidatastatic', Key='media/transmissions1.csv')
                        s3.upload_fileobj(buff2, 'intellidatastatic', 'media/transmissions1.csv')
                        print("Good File Upload Successful")

                    except FileNotFoundError:
                         print("The good file was not found")

                    except NoCredentialsError:
                         print("Credentials not available")


                           # create bad file
                    #with open('transmission_error.csv', 'w', newline='') as error_file:
                    #       writer = csv.writer(error_file)
                    #       writer.writerows(array1)

                    buff3 = io.StringIO()

                    writer = csv.writer(buff3, dialect='excel', delimiter=',')
                    writer.writerows(array_bad)

                    buff4 = io.BytesIO(buff3.getvalue().encode())


                        # save bad file to S3
                    try:
                        response = s3.delete_object(Bucket='intellidatastatic', Key='media/transmissions_error.csv')
                        s3.upload_fileobj(buff4, 'intellidatastatic', 'media/transmissions_error.csv')
                        print("Bad File Upload Successful")

                    except FileNotFoundError:
                        print("The bad file was not found")

                    except NoCredentialsError:
                        print("Credentials not available")

                    # load the transmission table
                    s3.download_file('intellidatastatic', 'media/transmissions1.csv', 'transmissions1.csv')

                    with open('transmissions1.csv', 'rt') as csv_file:
                        bulk_mgr = BulkCreateManager(chunk_size=20)

                        for row in csv.reader(csv_file):
                            if row[1] == "":
                                bulk_mgr.add(models.Transmission(transmissionid = str(uuid.uuid4())[26:36],
                                                          SenderName=row[2],
                                                          BenefitAdministratorPlatform=row[3],
                                                          ReceiverName=row[4],
                                                          create_date=row[5],
                                                          TestProductionCode=row[6],
                                                          TransmissionTypeCode=row[7],
                                                          SystemVersionIdentifier=row[8],
                                                          creator = request.user,
                                                          record_status = "Created",
                                                          bulk_upload_indicator = "Y"
                                                          ))
                            else:
                                bulk_mgr.add(models.Transmission(transmissionid = row[1],
                                                           SenderName=row[2],
                                                           BenefitAdministratorPlatform=row[3],
                                                           ReceiverName=row[4],
                                                           create_date=row[5],
                                                           TestProductionCode=row[6],
                                                           TransmissionTypeCode=row[7],
                                                           SystemVersionIdentifier=row[8],
                                                           creator = request.user,
                                                           record_status = "Created",
                                                           bulk_upload_indicator = "Y"

                                                          ))

                        bulk_mgr.done()

                        # load the transmission error table
                        s3.download_file('intellidatastatic', 'media/transmissions_error.csv', 'transmissions_error.csv')

                        #Refresh Error table for concerned employer
                        TransmissionError.objects.all().delete()

                        with open('transmissions_error.csv', 'rt') as csv_file:
                            bulk_mgr = BulkCreateManager(chunk_size=20)
                            for row1 in csv.reader(csv_file):
                                bulk_mgr.add(models.TransmissionError(serial = row1[0],
                                                          transmissionid=row1[1],
                                                          name=row1[2],
                                                          errorfield=row1[3],
                                                          error_description=row1[4],
                                                          creator = request.user,
                                                          source = ""
                                                          ))
                            bulk_mgr.done()


                    error_report = TransmissionErrorAggregate()

                    error_report.clean=Transmission.objects.count()
                    error_report.error=TransmissionError.objects.count()

                    error_report.total=(error_report.clean + error_report.error)

                    #Refresh Error aggregate table for concerned employer
                    TransmissionErrorAggregate.objects.all().delete()

                    error_report.save()



                    return HttpResponseRedirect(reverse("transmissions:all"))



                    #return HttpResponseRedirect(reverse("transmissions:all"))

        else:
                            # add form dictionary to context
                    context["form"] = form

                    return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("transmissions.add_transmission")
@login_required
def BulkUploadTransmission_deprecated(request):

    context ={}

    form = BulkUploadForm(request.POST, request.FILES)

    if form.is_valid():
                form.instance.creator = request.user
                form.save()

                #s3_resource = boto3.resource('s3')
                #s3_resource.Object("intellidatastatic", "media/transmissions.csv").download_file(f'/tmp/{"transmissions.csv"}') # Python 3.6+
                s3 = boto3.client('s3')
                s3.download_file('intellidatastatic', 'media/transmissions.csv', 'transmissions.csv')

                #with open('/tmp/{"transmissions.csv"}', 'rt') as csv_file:
                with open('transmissions.csv', 'rt') as csv_file:
                    bulk_mgr = BulkCreateManager(chunk_size=20)
                    for row in csv.reader(csv_file):
                        bulk_mgr.add(models.Transmission(

                                                  transmissionid = str(uuid.uuid4())[26:36],
                                                  name=row[0],
                                                  slug=slugify(row[0]),
                                                  type=row[1],
                                                  description=row[2],
                                                  description_html = misaka.html(row[2]),
                                                  coverage_limit=row[3],
                                                  price_per_1000_units=row[4],
                                                  creator = request.user,
                                                  record_status = "Created",
                                                  bulk_upload_indicator = "Y"
                                                  ))
                    bulk_mgr.done()

                return HttpResponseRedirect(reverse("transmissions:all"))
    else:
            # add form dictionary to context
            context["form"] = form

            return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("transmissions.add_transmission")
@login_required
def BulkUploadSOR(request):

    array = Transmission.objects.filter(bulk_upload_indicator='Y')
    serializer = TransmissionSerializer(array, many=True)
    json_array = serializer.data

    api = ApiDomains()
    url = api.transmission + "/" + "upload"
    #url='https://94q78vev60.execute-api.us-east-1.amazonaws.com/Prod/intellidatatransmissionAPI'
    #post data to the API for backend connection
    resp = requests.post(url, json=json_array)
    print("status code " + str(resp.status_code))

    if resp.status_code == 502:
        resp.status_code = 201

    obj = get_object_or_404(APICodes, http_response_code = resp.status_code)
    status_message=obj.http_response_message
    mesg=str(resp.status_code) + " - " + status_message

    if resp.status_code != 201:
        # This means something went wrong.
        message={'messages':mesg}
        return render(request, "messages.html", context=message)
    else:
        Transmission.objects.filter(bulk_upload_indicator='Y').update(bulk_upload_indicator=" ")
        return HttpResponseRedirect(reverse("transmissions:all"))


class ViewTransmissionErrorList(LoginRequiredMixin, generic.ListView):
    context_object_name = 'transmission_error_list'
    model = models.TransmissionError
    template_name = 'transmissions/transmission_error_list.html'

    #form_class = forms.MemberForm

    def get_queryset(self):
    #    return Member.objects.filter(employer=employer_name)
    #    return Member.objects.all
        #return models.Member.objects.prefetch_related('employer')
        return models.TransmissionError.objects.all()


@api_view(['GET', 'POST'])
def TransmissionList(request):

    if request.method == 'GET':
        contacts = Transmission.objects.all()
        serializer = TransmissionSerializer(contacts, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = TransmissionSerializer(data=request.data)
         # Raises a ValidatinException which will be sent as a 400 response.
        serializer.is_valid(raise_exception=True)
        transmission = Transmission()

        if serializer.data["transmissionid"] == '':
            transmission.transmissionid = str(uuid.uuid4())[26:36]
        else:
            transmission.transmissionid = serializer.data["transmissionid"]
        #transmission.transmissionid = serializer.data["transmissionid"]
        transmission.SenderName = serializer.data["SenderName"]
        transmission.BenefitAdministratorPlatform = serializer.data["BenefitAdministratorPlatform"]
        transmission.ReceiverName = serializer.data["ReceiverName"]
        transmission.TestProductionCode = serializer.data["TestProductionCode"]
        transmission.TransmissionTypeCode = serializer.data["TransmissionTypeCode"]
        transmission.SystemVersionIdentifier = serializer.data["SystemVersionIdentifier"]

        transmission.source = "API Call"

        transmission.creator = get_object_or_404(User, pk=serializer.data["creator"])
        #transmission.create_date = serializer.data["create_date"]
        transmission.backend_SOR_connection = "Disconnected"
        transmission.response = ""
        transmission.commit_indicator = "Not Committed"
        transmission.record_status = ""
        print(transmission)
        transmission.save()
        return Response(serializer.data)

    #if serializer.is_valid():
    #    serializer.save()

    #    return Response(serializer.data, status=status.HTTP_201_CREATED)

    #    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


#class for handling built-in API errors
class APIError(Exception):
    """An API Error Exception"""

    def __init__(self, status):
        self.status = status

    def __str__(self):
        return "APIError: status={}".format(self.status)
