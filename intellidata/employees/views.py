from django.contrib import messages
import datetime
from django.shortcuts import render
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.decorators import login_required
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
from employers.models import Employer
from employees.models import Employee
from transmissions.models import Transmission
from employees.models import EmployeeError
from employees.models import EmployeeErrorSerializer
from employees.models import EmployeeErrorAggregate
from . import models
from . import forms
from employees.forms import EmployeeForm
from bulkuploads.models import BulkUpload
from bulkuploads.forms import BulkUploadForm
import boto3
from botocore.exceptions import ClientError
import json
import csv
from employers.utils import BulkCreateManager
import os.path
from os import path
from django.utils.text import slugify
import misaka
import uuid
from employers.utils import ApiDomains
from apicodes.models import APICodes
from employers.utils import Notification
import requests
from django.contrib.auth.models import User
import re
from botocore.exceptions import NoCredentialsError
import io
from django.db.models import Count
from django.utils.encoding import smart_str

from events.forms import EventForm
from events.models import Event
from mandatories.models import Mandatory
from numchecks.models import Numcheck
from datetime import datetime

# For Rest rest_framework
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from employees.serializers import EmployeeSerializer


class SingleEmployee(LoginRequiredMixin, generic.DetailView):
    context_object_name = 'employee_details'
    model = models.Employee
    template_name = 'employees/employee_detail.html'
    #form_class = forms.employeeForm

class ListEmployees(LoginRequiredMixin, generic.ListView):
    context_object_name = 'employee_list'
    model = models.Employee
    template_name = 'employees/employee_list.html'

    #form_class = forms.employeeForm

    def get_queryset(self):
    #    return employee.objects.filter(employer=employer_name)
    #    return employee.objects.all
        return models.Employee.objects.prefetch_related('employer')


class CreateEmployee(LoginRequiredMixin, PermissionRequiredMixin, generic.CreateView):
    #fields = ("name", "age")
    permission_required = 'employees.add_employee'
    template_name = 'employees/employee_form.html'
    context_object_name = 'employee_details'
    redirect_field_name = 'employees/employee_detail.html'
    model = models.Employee
    form_class = forms.EmployeeForm

    def dispatch(self, request, *args, **kwargs):
        """
        Overridden so we can make sure the `Employer` instance exists
        before going any further.
        """
        self.employer = get_object_or_404(models.Employer, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):

        if not self.request.user.has_perm('employees.add_employee'):
            raise HttpResponseForbidden()
        else:
            """
            Overridden to add the employer relation to the `Employee` instance.
            """
            form.instance.creator = self.request.user
            form.instance.record_status = "Created"
            form.instance.source = "Online Transaction"
            form.instance.employerid=self.employer.employerid

            email_addr = form.instance.email
            phone_num = form.instance.mobile_phone

            #NOTIFY Employee
            notification = Notification()
            subscription_arn = notification.SubscribeEmployeeObj(phone_num)

            #Log events
            event = Event()
            event.EventTypeCode = "SUB"
            event.EventSubjectId = ""
            event.EventSubjectName = phone_num
            event.EventTypeReason = "Auto subscribed for push notification"
            event.source = "Online Transaction"
            event.creator=self.request.user
            event.save()

            notification.TextEmployeeObj(subscription_arn)

            #Log events
            event = Event()
            event.EventTypeCode = "SMS"
            event.EventSubjectId = ""
            event.EventSubjectName = ""
            event.EventTypeReason = "Auto push notification sent for the below auto subscription"
            event.source = "Online Transaction"
            event.creator=self.request.user
            event.save()


            notification.EmailEmployeeObj(email_addr)

            #Log events
            event = Event()
            event.EventTypeCode = "EML"
            event.EventSubjectId = ""
            event.EventSubjectName = email_addr
            event.EventTypeReason = "Auto email notification sent"
            event.source = "Online Transaction"
            event.creator=self.request.user
            event.save()

            form.instance.sms = "Initial notification sent"
            form.instance.emailer = "Initial notification sent"

            form.instance.employer = self.employer

            return super().form_valid(form)

#Pull from  backend system of record(SOR)
@permission_required("employees.add_employee")
@login_required
def BackendPull(request, pk):
        # fetch the object related to passed id

        employee_obj = get_object_or_404(Employee, pk = pk)

        api = ApiDomains()
        url = api.employee + "/" + "latest"
        payload={'ident': employee_obj.employeeid}
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

            #OVERRIDE THE OBJECT WITH API data
            obj.pk = int(json_data["LOCAL_ID"])
            obj.employeeid = json_data["EMPLOYEE_ID"]
            obj.ssn = json_data["SSN"]
            obj.name = json_data["NAME"]
            obj.name_html = misaka.html(obj.name)
            obj.gendercode = json_data["GENDERCODE"]
            obj.age = json_data["AGE"]
            obj.birthdate = json_data["BIRTHDATE"]
            obj.maritalstatus = json_data["MARITALSTATUS"]

            obj.home_address_line_1 = json_data["HOME_ADDRESS_LINE_1"]
            obj.home_address_line_2 = json_data["HOME_ADDRESS_LINE_2"]
            obj.home_city = json_data["HOME_CITY"]
            obj.home_state = json_data["HOME_STATE"]
            obj.home_zipcode = json_data["HOME_ZIPCODE"]

            obj.mail_address_line_1 = json_data["MAIL_ADDRESS_LINE_1"]
            obj.mail_address_line_2 = json_data["MAIL_ADDRESS_LINE_2"]
            obj.mail_city = json_data["MAIL_CITY"]
            obj.mail_state = json_data["MAIL_STATE"]
            obj.mail_zipcode = json_data["MAIL_ZIPCODE"]

            obj.work_address_line_1 = json_data["WORK_ADDRESS_LINE_1"]
            obj.work_address_line_2 = json_data["WORK_ADDRESS_LINE_2"]
            obj.work_city = json_data["WORK_CITY"]
            obj.work_state = json_data["WORK_STATE"]
            obj.work_zipcode = json_data["WORK_ZIPCODE"]

            obj.email = json_data["EMAIL"]
            obj.alternate_email = json_data["ALTERNATE_EMAIL"]

            obj.home_phone = json_data["HOME_PHONE"]
            obj.work_phone = json_data["WORK_PHONE"]
            obj.mobile_phone = json_data["MOBILE_PHONE"]

            obj.enrollment_method = json_data["ENROLLMENT_METHOD"]

            obj.employment_information = json_data["EMPLOYMENT_INFORMATION"]

            employer_id = json_data["EMPLOYER"]
            employer_obj = get_object_or_404(Employer, pk = employer_id)
            obj.employer = employer_obj

            obj.source = json_data["SOURCE"]
            obj.employerid = json_data["EMPLOYERID"]

            obj.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            obj.employee_date = json_data["EMPLOYEE_DATE"]

            obj.sms = json_data["SMS"]
            obj.emailer = json_data["EMAILER"]
            obj.artefact = json_data["ARTEFACT"]

            obj.backend_SOR_connection = json_data["CONNECTION"]
            obj.response = json_data["RESPONSE"]
            obj.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj.record_status = json_data["RECORD_STATUS"]

            context = {'employee_details':obj}

            return render(request, "employees/employee_detail.html", context=context)



#Pull from  backend system of record(SOR)
@permission_required("employees.add_employee")
@login_required
def ListEmployeesHistory(request, pk):

                context ={}

                employee_obj = get_object_or_404(Employee, pk = pk)

                api = ApiDomains()
                url = api.employee + "/" + "history"

                payload={'ident': employee_obj.employeeid}

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
                     obj = Employee()
                      #dict_data.append(json.loads(json_data[ix]))
                     obj.pk = int(json_data[ix]["LOCAL_ID"])
                     obj.employeeid = json_data[ix]["EMPLOYEE_ID"]
                     obj.ssn = json_data[ix]["SSN"]
                     obj.name = json_data[ix]["NAME"]
                     obj.name_html = misaka.html(obj.name)
                     obj.gendercode = json_data[ix]["GENDERCODE"]
                     obj.age = json_data[ix]["AGE"]
                     obj.birthdate = json_data[ix]["BIRTHDATE"]
                     obj.maritalstatus = json_data[ix]["MARITALSTATUS"]

                     obj.home_address_line_1 = json_data[ix]["HOME_ADDRESS_LINE_1"]
                     obj.home_address_line_2 = json_data[ix]["HOME_ADDRESS_LINE_2"]
                     obj.home_city = json_data[ix]["HOME_CITY"]
                     obj.home_state = json_data[ix]["HOME_STATE"]
                     obj.home_zipcode = json_data[ix]["HOME_ZIPCODE"]

                     obj.mail_address_line_1 = json_data[ix]["MAIL_ADDRESS_LINE_1"]
                     obj.mail_address_line_2 = json_data[ix]["MAIL_ADDRESS_LINE_2"]
                     obj.mail_city = json_data[ix]["MAIL_CITY"]
                     obj.mail_state = json_data[ix]["MAIL_STATE"]
                     obj.mail_zipcode = json_data[ix]["MAIL_ZIPCODE"]

                     obj.work_address_line_1 = json_data[ix]["WORK_ADDRESS_LINE_1"]
                     obj.work_address_line_2 = json_data[ix]["WORK_ADDRESS_LINE_2"]
                     obj.work_city = json_data[ix]["WORK_CITY"]
                     obj.work_state = json_data[ix]["WORK_STATE"]
                     obj.work_zipcode = json_data[ix]["WORK_ZIPCODE"]

                     obj.email = json_data[ix]["EMAIL"]
                     obj.alternate_email = json_data[ix]["ALTERNATE_EMAIL"]

                     obj.home_phone = json_data[ix]["HOME_PHONE"]
                     obj.work_phone = json_data[ix]["WORK_PHONE"]
                     obj.mobile_phone = json_data[ix]["MOBILE_PHONE"]

                     obj.enrollment_method = json_data[ix]["ENROLLMENT_METHOD"]

                     obj.employment_information = json_data[ix]["EMPLOYMENT_INFORMATION"]

                     employer_id = json_data[ix]["EMPLOYER"]
                     employer_obj = get_object_or_404(Employer, pk = employer_id)
                     obj.employer = employer_obj
                     obj.source = json_data[ix]["SOURCE"]
                     obj.employerid = json_data[ix]["EMPLOYERID"]

                     obj.creator = User.objects.get(pk=int(json_data[ix]["CREATOR"]))
                     obj.employee_date = json_data[ix]["EMPLOYEE_DATE"]

                     obj.sms = json_data[ix]["SMS"]
                     obj.emailer = json_data[ix]["EMAILER"]
                     obj.artefact = json_data[ix]["ARTEFACT"]

                     obj.backend_SOR_connection = json_data[ix]["CONNECTION"]
                     obj.response = json_data[ix]["RESPONSE"]
                     obj.commit_indicator = json_data[ix]["COMMIT_INDICATOR"]
                     obj.record_status = json_data[ix]["RECORD_STATUS"]

                     obj_data.append(obj)

                    context = {'object_list':obj_data}

                    return render(request, "employees/employee_list.html", context=context)

                    #mesg_obj = get_object_or_404(APICodes, http_response_code = 1000)
                    #status_message=mesg_obj.http_response_message
                    #mesg="1000" + " - " + status_message
                    # add form dictionary to context
                    #message={'messages':mesg}
                    #return render(request, "messages.html", context=message)


@permission_required("employees.add_employee")
@login_required
def RefreshEmployee(request, pk):
        # fetch the object related to passed id
        context ={}
        employee_obj = get_object_or_404(Employee, pk = pk)

        api = ApiDomains()
        url = api.employee + "/" + "refresh"

        payload={'ident': employee_obj.employeeid}

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
            obj1=Employee()

            #OVERRIDE THE OBJECT WITH API data
            obj1.pk = int(json_data["LOCAL_ID"])
            obj1.employeeid = json_data["EMPLOYEE_ID"]
            obj1.ssn = json_data["SSN"]
            obj1.name = json_data["NAME"]
            obj1.name_html = misaka.html(obj1.name)
            obj1.gendercode = json_data["GENDERCODE"]
            obj1.age = json_data["AGE"]
            obj1.birthdate = json_data["BIRTHDATE"]
            obj1.maritalstatus = json_data["MARITALSTATUS"]

            obj1.home_address_line_1 = json_data["HOME_ADDRESS_LINE_1"]
            obj1.home_address_line_2 = json_data["HOME_ADDRESS_LINE_2"]
            obj1.home_city = json_data["HOME_CITY"]
            obj1.home_state = json_data["HOME_STATE"]
            obj1.home_zipcode = json_data["HOME_ZIPCODE"]

            obj1.mail_address_line_1 = json_data["MAIL_ADDRESS_LINE_1"]
            obj1.mail_address_line_2 = json_data["MAIL_ADDRESS_LINE_2"]
            obj1.mail_city = json_data["MAIL_CITY"]
            obj1.mail_state = json_data["MAIL_STATE"]
            obj1.mail_zipcode = json_data["MAIL_ZIPCODE"]

            obj1.work_address_line_1 = json_data["WORK_ADDRESS_LINE_1"]
            obj1.work_address_line_2 = json_data["WORK_ADDRESS_LINE_2"]
            obj1.work_city = json_data["WORK_CITY"]
            obj1.work_state = json_data["WORK_STATE"]
            obj1.work_zipcode = json_data["WORK_ZIPCODE"]

            obj1.email = json_data["EMAIL"]
            obj1.alternate_email = json_data["ALTERNATE_EMAIL"]

            obj1.home_phone = json_data["HOME_PHONE"]
            obj1.work_phone = json_data["WORK_PHONE"]
            obj1.mobile_phone = json_data["MOBILE_PHONE"]

            obj1.enrollment_method = json_data["ENROLLMENT_METHOD"]

            obj1.employment_information = json_data["EMPLOYMENT_INFORMATION"]

            employer_id = json_data["EMPLOYER"]
            employer_obj = get_object_or_404(Employer, pk = employer_id)
            obj1.employer = employer_obj
            obj1.source = json_data["SOURCE"]
            obj1.employerid = json_data["EMPLOYERID"]

            obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            obj1.employee_date = json_data["EMPLOYEE_DATE"]

            obj1.sms = json_data["SMS"]
            obj1.emailer = json_data["EMAILER"]
            obj1.artefact = json_data["ARTEFACT"]

            obj1.backend_SOR_connection = json_data["CONNECTION"]
            obj1.response = json_data["RESPONSE"]
            obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj1.record_status = json_data["RECORD_STATUS"]

            #Log events
            event = Event()
            event.EventTypeCode = "EER"
            event.EventSubjectId = obj1.employeeid
            event.EventSubjectName = obj1.name
            event.EventTypeReason = "Employee refreshed from ODS"
            event.source = "Online Transaction"
            event.creator=obj1.creator
            event.save()

            obj1.save()

            context = {'employee_details':obj1}

            return render(request, "employees/employee_detail.html", context=context)



@login_required
@permission_required("employees.add_employee")
def VersionEmployee(request, pk):
    # dictionary for initial data with
    # field names as keys
    context ={}

    # fetch the object related to passed id
    obj = get_object_or_404(Employee, pk = pk)

    # pass the object as instance in form
    form = EmployeeForm(request.POST or None, instance = obj)

    # save the data from the form and
    # redirect to detail_view
    if form.is_valid():
            obj.pk = int(round(time.time() * 1000))
            form.instance.creator = request.user
            form.instance.record_status = "Created"
            form.instance.employerid=form.instance.employer.employerid

            #Log events
            event = Event()
            event.EventTypeCode = "EEV"
            event.EventSubjectId = form.instance.employeeid
            event.EventSubjectName = form.instance.name
            event.EventTypeReason = "Employee versioned"
            event.source = "Online Transaction"
            event.creator=request.user
            event.save()

            form.save()
            return HttpResponseRedirect(reverse("employees:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "employees/employee_form.html", context)


class UpdateEmployee(LoginRequiredMixin, PermissionRequiredMixin, generic.UpdateView):
    #fields = ("name", "age")
    permission_required = 'employees.change_employee'
    template_name = 'employees/employee_form.html'
    #context_object_name = 'employee_details'
    redirect_field_name = 'employees/employee_detail.html'
    model = models.Employee
    form_class = forms.EmployeeForm

    def form_valid(self, form):

        if not self.request.user.has_perm('employees.change_employee'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            form.instance.record_status = "Updated"

            #Log events
            event = Event()
            event.EventTypeCode = "EEU"
            event.EventSubjectId = form.instance.employeeid
            event.EventSubjectName = form.instance.name
            event.EventTypeReason = "Employee updated"
            event.source = "Online Transaction"
            event.creator=self.request.user
            event.save()

            return super().form_valid(form)


class DeleteEmployee(LoginRequiredMixin, PermissionRequiredMixin, generic.DeleteView,):
    permission_required = 'employees.delete_employee'
    context_object_name = 'employee_details'
    form_class = forms.EmployeeForm
    model = models.Employee
    template_name = 'employees/employee_delete_confirm.html'
    success_url = reverse_lazy("employees:all")


    def delete(self, *args, **kwargs):
        messages.success(self.request, "Employee Deleted")
        return super().delete(*args, **kwargs)

    def form_valid(self, form):

        if not self.request.user.has_perm('employees.delete_employee'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user

            #Log events
            event = Event()
            event.EventTypeCode = "ERD"
            event.EventSubjectId = form.instance.employerid
            event.EventSubjectName = form.instance.name
            event.EventTypeReason = "Employee deleted"
            event.source = "Online Transaction"
            event.creator=self.request.user
            event.save()

            return super().form_valid(form)


def SearchEmployeesForm(request):
    return render(request,'employees/employee_search_form.html')


class SearchEmployeesList(LoginRequiredMixin, generic.ListView):
    login_url = '/login/'
    model = models.Employee
    template_name = 'employees/employee_search_list.html'

    def get_queryset(self, **kwargs): # new
        query = self.request.GET.get('q', None)
        object_list = models.Employee.objects.filter(
            Q(name__icontains=query) | Q(age__icontains=query) | Q(employeeid__icontains=query) | Q(home_address_line_1__icontains=query) | Q(home_city__icontains=query) | Q(home_state__icontains=query) | Q(home_zipcode__icontains=query) | Q(mail_address_line_1__icontains=query) | Q(mail_city__icontains=query) | Q(mail_state__icontains=query) | Q(mail_zipcode__icontains=query) | Q(work_address_line_1__icontains=query) | Q(work_city__icontains=query) | Q(work_state__icontains=query) | Q(work_zipcode__icontains=query) | Q(email__icontains=query) | Q(alternate_email__icontains=query) | Q(home_phone__icontains=query) | Q(work_phone__icontains=query) | Q(mobile_phone__icontains=query) | Q(enrollment_method__icontains=query) | Q(employment_information__icontains=query)
        )

        #change start for remote SearchEmployeesForm
        if not object_list:
            api = ApiDomains()
            url = api.employee + "/" + "refresh"

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
                obj1=Employee()

                #OVERRIDE THE OBJECT WITH API data
                obj1.pk = int(json_data["LOCAL_ID"])
                obj1.employeeid = json_data["EMPLOYEE_ID"]
                obj1.ssn = json_data["SSN"]
                obj1.name = json_data["NAME"]
                obj1.name_html = misaka.html(obj.name)
                obj1.gendercode = json_data["GENDERCODE"]
                obj1.age = json_data["AGE"]
                obj1.birthdate = json_data["BIRTHDATE"]
                obj1.maritalstatus = json_data["MARITALSTATUS"]

                obj1.home_address_line_1 = json_data["HOME_ADDRESS_LINE_1"]
                obj1.home_address_line_2 = json_data["HOME_ADDRESS_LINE_2"]
                obj1.home_city = json_data["HOME_CITY"]
                obj1.home_state = json_data["HOME_STATE"]
                obj1.home_zipcode = json_data["HOME_ZIPCODE"]

                obj1.mail_address_line_1 = json_data["MAIL_ADDRESS_LINE_1"]
                obj1.mail_address_line_2 = json_data["MAIL_ADDRESS_LINE_2"]
                obj1.mail_city = json_data["MAIL_CITY"]
                obj1.mail_state = json_data["MAIL_STATE"]
                obj1.mail_zipcode = json_data["MAIL_ZIPCODE"]

                obj1.work_address_line_1 = json_data["WORK_ADDRESS_LINE_1"]
                obj1.work_address_line_2 = json_data["WORK_ADDRESS_LINE_2"]
                obj1.work_city = json_data["WORK_CITY"]
                obj1.work_state = json_data["WORK_STATE"]
                obj1.work_zipcode = json_data["WORK_ZIPCODE"]

                obj1.email = json_data["EMAIL"]
                obj1.alternate_email = json_data["ALTERNATE_EMAIL"]

                obj1.home_phone = json_data["HOME_PHONE"]
                obj1.work_phone = json_data["WORK_PHONE"]
                obj1.mobile_phone = json_data["MOBILE_PHONE"]

                obj1.enrollment_method = json_data["ENROLLMENT_METHOD"]

                obj1.employment_information = json_data["EMPLOYMENT_INFORMATION"]

                employer_id = json_data["EMPLOYER"]
                employer_obj = get_object_or_404(Employer, pk = employer_id)
                obj1.employer = employer_obj
                obj1.source = json_data["SOURCE"]
                obj1.employerid = json_data["EMPLOYERID"]

                obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
                obj1.employee_date = json_data["EMPLOYEE_DATE"]

                obj1.sms = json_data["SMS"]
                obj1.emailer = json_data["EMAILER"]
                obj1.artefact = json_data["ARTEFACT"]

                obj1.backend_SOR_connection = json_data["CONNECTION"]
                obj1.response = json_data["RESPONSE"]
                obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
                obj1.record_status = json_data["RECORD_STATUS"]

                obj1.save()

                object_remote_list = Employee.objects.filter(employeeid=query)
                print(object_remote_list)
                return object_remote_list

        else:
        #change end for remote SearchEmployeesForm

                return object_list


@permission_required("employees.add_employee")
@login_required
def BulkUploadEmployee(request, pk, *args, **kwargs):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        transmission_pk=Employer.objects.get(pk=pk).transmission_id
        transmissionid=Transmission.objects.get(pk=transmission_pk).transmissionid
        sendername=Transmission.objects.get(pk=transmission_pk).SenderName
        print(transmissionid)
        print(sendername)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.client('s3')
                    s3.download_file('intellidatastatic1', 'media/employees.csv', 'employees.csv')

                    with open('employees.csv', 'rt') as csv_file:
                        array_good =[]
                        array_bad =[]
                        #array_bad = ["Serial#", "Employee_id", "Name", "Errorfield", "Description", "Employer_id", "Tramsmission_id", "Sender_Name"]

                        next(csv_file) # skip header line
                        execution_start_time = datetime.now()
                        for row in csv.reader(csv_file):
                                                      bad_ind = 0
                                                      array1=[]
                                                      array2=[]

                                                      #populate serial number
                                                      serial=row[0]
                                                      array2.append(serial)

                                                    #pass employee:
                                                      employeeid=row[1]
                                                      array2.append(employeeid)

                                                      name=row[3]
                                                      ssn=row[2]
                                                      if (Mandatory.objects.filter(attributes='employee_ssn').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_ssn')[0].required
                                                          if (var == "Yes" and ssn ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "SSN is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(ssn)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(ssn)
                                                      else:
                                                              array2.append(ssn)

                                                      #employerid=row[30]

                                                       #validate name
                                                      name=row[3]
                                                      array1=[]
                                                      if name == "":
                                                          bad_ind = 1
                                                          description = "Name is mandatory"
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(name)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)

                                                      else:
                                                          array2.append(name)

                                                      slug=slugify(row[3])
                                                      #array2.append(slug)

                                                      gendercode=row[4]
                                                      if (Mandatory.objects.filter(attributes='employee_gendercode').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_gendercode')[0].required
                                                          if (var == "Yes" and gendercode ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "Gendercode is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(gendercode)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(gendercode)
                                                      else:
                                                              array2.append(gendercode)

                                                      #validate age
                                                      age=int(row[5])
                                                      array1=[]
                                                      if age == "":
                                                          bad_ind=1
                                                          description = "Age must be numeric "
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(age)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      elif (age <= 0 or age >= 100):
                                                          bad_ind=1
                                                          description = "Age must be between 1 and 99 years "
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(age)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      else:
                                                           array2.append(age)

                                                      birthdate=row[6]
                                                      if (Mandatory.objects.filter(attributes='employee_birthdate').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_birthdate')[0].required
                                                          if (var == "Yes" and birthdate ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "Birthdate is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(birthdate)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(birthdate)
                                                      else:
                                                              array2.append(birthdate)

                                                      maritalstatus=row[7]
                                                      if (Mandatory.objects.filter(attributes='employee_maritalstatus').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_maritalstatus')[0].required
                                                          if (var == "Yes" and maritalstatus ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "Marital status is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(maritalstatus)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(maritalstatus)
                                                      else:
                                                              array2.append(maritalstatus)

                                                      #validate address line 1
                                                      home_address_line_1=row[8]
                                                      array1=[]
                                                      if home_address_line_1 == "":
                                                          bad_ind = 1
                                                          description = "Home address line 1 is mandatory"
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(home_address_line_1)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      else:
                                                          array2.append(home_address_line_1)


                                                      #validate address line 2
                                                      home_address_line_2=row[9]
                                                      if (Mandatory.objects.filter(attributes='employee_home_address_line_2').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_home_address_line_2')[0].required
                                                          if (var == "Yes" and home_address_line_2 ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "Home address 2 is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(home_address_line_2)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(home_address_line_2)
                                                      else:
                                                              array2.append(home_address_line_2)

                                                           #validate city
                                                      home_city=row[10]
                                                      array1=[]
                                                      if home_city == "":
                                                           bad_ind = 1
                                                           description = "Home city is mandatory"
                                                           array1.append(serial)
                                                           array1.append(employeeid)
                                                           array1.append(name)
                                                           array1.append(home_city)
                                                           array1.append(description)
                                                           array1.append(pk)
                                                           array1.append(Employer.objects.get(pk=pk).employerid)
                                                           array1.append(transmissionid)
                                                           array1.append(sendername)
                                                           array_bad.append(array1)
                                                      else:
                                                           array2.append(home_city)

                                                           #validate state
                                                      home_state=row[11]
                                                      array1=[]
                                                      if home_state == "":
                                                           bad_ind = 1
                                                           description = "Home state is mandatory"
                                                           array1.append(serial)
                                                           array1.append(employeeid)
                                                           array1.append(name)
                                                           array1.append(home_state)
                                                           array1.append(description)
                                                           array1.append(pk)
                                                           array1.append(Employer.objects.get(pk=pk).employerid)
                                                           array1.append(transmissionid)
                                                           array1.append(sendername)
                                                           array_bad.append(array1)
                                                      else:
                                                          array2.append(home_state)

                                                          #validate zipcode
                                                      home_zipcode=row[12]
                                                      array1=[]
                                                      if home_zipcode == "":
                                                            bad_ind = 1
                                                            description = "Zipcode is mandatory"
                                                            array1.append(serial)
                                                            array1.append(employeeid)
                                                            array1.append(name)
                                                            array1.append(home_zipcode)
                                                            array1.append(description)
                                                            array1.append(pk)
                                                            array1.append(Employer.objects.get(pk=pk).employerid)
                                                            array1.append(transmissionid)
                                                            array1.append(sendername)
                                                            array_bad.append(array1)
                                                      else:
                                                           array2.append(home_zipcode)

                                                      mail_address_line_1=row[13]
                                                      if (Mandatory.objects.filter(attributes='employee_mail_address_line_1').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_mail_address_line_1')[0].required
                                                          if (var == "Yes" and mail_address_line_1 ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "Mail_address_line_1 is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(mail_address_line_1)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(mail_address_line_1)
                                                      else:
                                                              array2.append(mail_address_line_1)

                                                      mail_address_line_2=row[14]
                                                      if (Mandatory.objects.filter(attributes='employee_mail_address_line_2').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_mail_address_line_2')[0].required
                                                          if (var == "Yes" and mail_address_line_2 ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "mail_address_line_2 is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(mail_address_line_2)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(mail_address_line_2)
                                                      else:
                                                              array2.append(mail_address_line_2)

                                                      mail_city=row[15]
                                                      if (Mandatory.objects.filter(attributes='employee_mail_city').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_mail_city')[0].required
                                                          if (var == "Yes" and mail_city ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "mail_city is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(mail_city)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(mail_city)
                                                      else:
                                                              array2.append(mail_city)

                                                      mail_state=row[16]
                                                      if (Mandatory.objects.filter(attributes='employee_mail_state').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_mail_state')[0].required
                                                          if (var == "Yes" and mail_state ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "mail_state is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(mail_state)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(mail_state)
                                                      else:
                                                              array2.append(mail_state)

                                                      mail_zipcode=row[17]
                                                      if (Mandatory.objects.filter(attributes='employee_mail_zipcode').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_mail_zipcode')[0].required
                                                          if (var == "Yes" and mail_zipcode ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "mail_zipcode is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(mail_zipcode)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(mail_zipcode)
                                                      else:
                                                              array2.append(mail_zipcode)

                                                      work_address_line_1=row[18]
                                                      if (Mandatory.objects.filter(attributes='employee_work_address_line_1').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_address_line_1')[0].required
                                                          if (var == "Yes" and work_address_line_1 ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_address_line_1 is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_address_line_1)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_address_line_1)
                                                      else:
                                                              array2.append(work_address_line_1)

                                                      work_address_line_2=row[19]
                                                      if (Mandatory.objects.filter(attributes='employee_work_address_line_2').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_address_line_2')[0].required
                                                          if (var == "Yes" and work_address_line_2 ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_address_line_2 is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_address_line_2)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_address_line_2)
                                                      else:
                                                              array2.append(work_address_line_2)

                                                      work_city=row[20]
                                                      if (Mandatory.objects.filter(attributes='employee_work_city').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_city')[0].required
                                                          if (var == "Yes" and work_city ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_city is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_city)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_city)
                                                      else:
                                                              array2.append(work_city)

                                                      work_state=row[21]
                                                      if (Mandatory.objects.filter(attributes='employee_work_state').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_state')[0].required
                                                          if (var == "Yes" and work_state ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_state is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_state)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_state)
                                                      else:
                                                              array2.append(work_state)

                                                      work_zipcode=row[22]
                                                      if (Mandatory.objects.filter(attributes='employee_work_zipcode').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_zipcode')[0].required
                                                          if (var == "Yes" and work_zipcode ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_zipcode is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_zipcode)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_zipcode)
                                                      else:
                                                              array2.append(work_zipcode)


                                                            #validate email
                                                      email=row[23]
                                                      array1=[]
                                                      if email == "":
                                                          bad_ind=1
                                                          description = "Email is mandatory "
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(email)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      elif not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", email):
                                                          bad_ind = 1
                                                          description = "Invalid email"
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(email)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      else:
                                                          array2.append(email)

                                                      alternate_email=row[24]
                                                      if (Mandatory.objects.filter(attributes='employee_alternate_email').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_alternate_email')[0].required
                                                          if (var == "Yes" and alternate_email ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "alternate_email is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(alternate_email)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(alternate_email)
                                                      else:
                                                              array2.append(alternate_email)

                                                      #validate phone
                                                      home_phone=row[25]
                                                      if (Mandatory.objects.filter(attributes='employee_home_phone').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_home_phone')[0].required
                                                          if (var == "Yes" and home_phone ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "home_phone is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(home_phone)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(home_phone)
                                                      else:
                                                              array2.append(home_phone)


                                                      work_phone=row[26]
                                                      if (Mandatory.objects.filter(attributes='employee_work_phone').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_work_phone')[0].required
                                                          if (var == "Yes" and work_phone ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "work_phone is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(work_phone)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(work_phone)
                                                      else:
                                                              array2.append(work_phone)

                                                      mobile_phone=row[27]
                                                      array1=[]
                                                      p=[]
                                                      p = mobile_phone
                                                      if p.isnumeric() == False:
                                                          bad_ind=1
                                                          description = "Mobile phone must be numbers "
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(mobile_phone)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      elif len(p) != (10 and 11):
                                                          print(len(p))
                                                          bad_ind=1
                                                          description = "Length of mobile phone number is not correct "
                                                          array1.append(serial)
                                                          array1.append(employeeid)
                                                          array1.append(name)
                                                          array1.append(mobile_phone)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array1.append(Employer.objects.get(pk=pk).employerid)
                                                          array1.append(transmissionid)
                                                          array1.append(sendername)
                                                          array_bad.append(array1)
                                                      else:
                                                           array2.append(mobile_phone)


                                                      enrollment_method=row[28]
                                                      if (Mandatory.objects.filter(attributes='employee_enrollment_method').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_enrollment_method')[0].required
                                                          if (var == "Yes" and enrollment_method ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "enrollment_method is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(enrollment_method)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(enrollment_method)
                                                      else:
                                                              array2.append(enrollment_method)

                                                      employment_information=row[29]
                                                      if (Mandatory.objects.filter(attributes='employee_employment_information').exists()):
                                                          var=Mandatory.objects.filter(attributes='employee_employment_information')[0].required
                                                          if (var == "Yes" and employment_information ==""):
                                                               array1=[]
                                                               bad_ind = 1
                                                               description = "employment_information is mandatory"
                                                               array1.append(serial)
                                                               array1.append(employeeid)
                                                               array1.append(name)
                                                               array1.append(employment_information)
                                                               array1.append(description)
                                                               array1.append(pk)
                                                               array1.append(Employer.objects.get(pk=pk).employerid)
                                                               array1.append(transmissionid)
                                                               array1.append(sendername)
                                                               array_bad.append(array1)
                                                          else:
                                                               array2.append(employment_information)
                                                      else:
                                                              array2.append(employment_information)


                                                      if bad_ind == 0:
                                                          array_good.append(array2)



                        # create good file
                    #with open('employees1.csv', 'w', newline='') as clean_file:
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
                        response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees1.csv')
                        s3.upload_fileobj(buff2, 'intellidatastatic1', 'media/employees1.csv')
                        print("Good File Upload Successful")

                    except FileNotFoundError:
                         print("The good file was not found")

                    except NoCredentialsError:
                         print("Credentials not available")


                           # create bad file
                    #with open('employee_error.csv', 'w', newline='') as error_file:
                    #       writer = csv.writer(error_file)
                    #       writer.writerows(array1)

                    buff3 = io.StringIO()

                    writer = csv.writer(buff3, dialect='excel', delimiter=',')
                    writer.writerows(array_bad)

                    buff4 = io.BytesIO(buff3.getvalue().encode())


                        # save bad file to S3
                    try:
                        response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees_error.csv')
                        s3.upload_fileobj(buff4, 'intellidatastatic1', 'media/employees_error.csv')
                        print("Bad File Upload Successful")

                    except FileNotFoundError:
                        print("The bad file was not found")

                    except NoCredentialsError:
                        print("Credentials not available")

                    # load the employee table
                    s3.download_file('intellidatastatic1', 'media/employees1.csv', 'employees1.csv')

                    with open('employees1.csv', 'rt') as csv_file:
                        bulk_mgr = BulkCreateManager(chunk_size=20)
                        notification = Notification()
                        for row in csv.reader(csv_file):
                            if row[1] == "":
                                bulk_mgr.add(models.Employee(employeeid = str(uuid.uuid4())[26:36],
                                                          ssn=row[2],
                                                          name=row[3],
                                                          slug=slugify(row[3]),
                                                          gendercode=row[4],
                                                          age=int(row[5]),
                                                          birthdate=row[6],
                                                          maritalstatus=row[7],
                                                          home_address_line_1=row[8],
                                                          home_address_line_2=row[9],
                                                          home_city=row[10],
                                                          home_state=row[11],
                                                          home_zipcode=row[12],
                                                          mail_address_line_1=row[13],
                                                          mail_address_line_2=row[14],
                                                          mail_city=row[15],
                                                          mail_state=row[16],
                                                          mail_zipcode=row[17],
                                                          work_address_line_1=row[18],
                                                          work_address_line_2=row[19],
                                                          work_city=row[20],
                                                          work_state=row[21],
                                                          work_zipcode=row[22],
                                                          email=row[23],
                                                          alternate_email=row[24],
                                                          home_phone=row[25],
                                                          work_phone=row[26],
                                                          mobile_phone=row[27],
                                                          enrollment_method=row[28],
                                                          employment_information=row[29],
                                                          employer=get_object_or_404(models.Employer, pk=pk),
                                                          employerid=(models.Employer.objects.get(pk=pk).employerid),
                                                          creator = request.user,
                                                          sms="Initial notification sent",
                                                          emailer="Initial notification sent",
                                                          source="Standard Feed Bulk Upload",
                                                          record_status = "Created",
                                                          bulk_upload_indicator = "Y"
                                                          ))
                            else:
                                bulk_mgr.add(models.Employee(employeeid = row[1],
                                                          ssn=row[2],
                                                          name=row[3],
                                                          slug=slugify(row[3]),
                                                          gendercode=row[4],
                                                          age=int(row[5]),
                                                          birthdate=row[6],
                                                          maritalstatus=row[7],
                                                          home_address_line_1=row[8],
                                                          home_address_line_2=row[9],
                                                          home_city=row[10],
                                                          home_state=row[11],
                                                          home_zipcode=row[12],
                                                          mail_address_line_1=row[13],
                                                          mail_address_line_2=row[14],
                                                          mail_city=row[15],
                                                          mail_state=row[16],
                                                          mail_zipcode=row[17],
                                                          work_address_line_1=row[18],
                                                          work_address_line_2=row[19],
                                                          work_city=row[20],
                                                          work_state=row[21],
                                                          work_zipcode=row[22],
                                                          email=row[23],
                                                          alternate_email=row[24],
                                                          home_phone=row[25],
                                                          work_phone=row[26],
                                                          mobile_phone=row[27],
                                                          enrollment_method=row[28],
                                                          employment_information=row[29],
                                                          employer=get_object_or_404(models.Employer, pk=pk),
                                                          employerid=(models.Employer.objects.get(pk=pk).employerid),
                                                          creator = request.user,
                                                          sms="Initial notification sent",
                                                          emailer="Initial notification sent",
                                                          source="Standard Feed Bulk Upload",
                                                          record_status = "Created",
                                                          bulk_upload_indicator = "Y"
                                                          ))

                        bulk_mgr.done()

                    with open('employees1.csv', 'rt') as csv_file:
                        for ix in csv.reader(csv_file):

                                #NOTIFY Employee
                                mobile_phone=ix[27]
                                subscription_arn = notification.SubscribeEmployeeObj(mobile_phone)

                                #Log events
                                event = Event()
                                event.EventTypeCode = "SUB"
                                event.EventSubjectId = ""
                                event.EventSubjectName = mobile_phone
                                event.EventTypeReason = "Auto subscribed for push notification"
                                event.source = "Standard Feed Bulk Upload"
                                event.creator=request.user
                                event.save()

                                notification.TextEmployeeObj(subscription_arn)

                                #Log events
                                event = Event()
                                event.EventTypeCode = "SMS"
                                event.EventSubjectId = ""
                                event.EventSubjectName = ""
                                event.EventTypeReason = "Auto push notification sent for the below auto subscription"
                                event.source = "Standard Feed Bulk Upload"
                                event.creator=request.user
                                event.save()

                                #send email
                                email=ix[23]
                                notification.EmailEmployeeObj(email)

                                #Log events

                                event = Event()
                                event.EventTypeCode = "EML"
                                event.EventSubjectId = ""
                                event.EventSubjectName = email
                                event.EventTypeReason = "Auto email notification sent"
                                event.source = "Standard Feed Bulk Upload"
                                event.creator=request.user
                                event.save()



                    # load the employee error table
                    s3.download_file('intellidatastatic1', 'media/employees_error.csv', 'employees_error.csv')

                    if (os.stat("employees_error.csv").st_size != 0):
                        email_address=models.Employer.objects.get(pk=pk).planadmin_email
                        if (email_address!="" and email_address!=None):
                            employer_name=models.Employer.objects.get(pk=pk).name
                            attached_file = employer_name + "_employee_feed_error"
                            attachment_file = "employees_error.csv"
                            notification.EmailPlanAdmin(email_address, attachment_file, attached_file)



                    #Refresh Error table for concerned employer
                    #EmployeeError.objects.filter(employer_id=pk).delete()
                    EmployeeError.objects.all().delete()

                    with open('employees_error.csv', 'rt') as csv_file:
                            bulk_mgr = BulkCreateManager(chunk_size=20)
                            for row1 in csv.reader(csv_file):
                                bulk_mgr.add(models.EmployeeError(serial = row1[0],
                                                          employeeid=row1[1],
                                                          name=row1[2],
                                                          errorfield=row1[3],
                                                          description=row1[4],
                                                          employer=get_object_or_404(models.Employer, pk=row1[5]),
                                                          employerid=row1[6],
                                                          transmissionid=row1[7],
                                                          sendername=row1[8],
                                                          creator = request.user,
                                                          source="Standard Feed Bulk Upload"
                                                          ))
                            bulk_mgr.done()


                    execution_end_time = datetime.now()
                    duration = (execution_end_time - execution_start_time)

                    error_report = EmployeeErrorAggregate()
                    error_report.employer = get_object_or_404(Employer, pk=pk)

                    error_report.processed_clean=Employee.objects.filter(employer_id=pk).count()
                    error_report.number_of_error_occurences=EmployeeError.objects.filter(employer_id=pk).count()

                    #distinct = EmployeeError.objects.filter(employer_id=pk).values('serial').annotate(serial_count=Count('serial')).filter(serial_count=1)
                    #records = EmployeeError.objects.filter(serial__in=[item['serial'] for item in distinct]).count()
                    #error_report.error=records


                    error_report.total_employees_till_date=(error_report.processed_clean + error_report.number_of_error_occurences)

                    error_report.execution_time_for_this_run=duration

                    with open('employees.csv', 'rt') as csv_file:
                        next(csv_file) # skip header line
                        lines= len(list(csv_file))
                        print(lines)
                        error_report.volume_processed_in_this_run=lines

                    #Refresh Error aggregate table for concerned employer
                    #EmployeeErrorAggregate.objects.filter(employer_id=pk).delete()


                    error_report.save()

                    #Log events
                    event = Event()
                    event.EventTypeCode = "EEB"
                    event.EventSubjectId = "bulkemployees"
                    event.EventSubjectName = "Bulk processing"
                    event.EventTypeReason = "Employees uploaded in bulk"
                    event.source = "Standard Feed Bulk Upload"
                    event.creator=request.user
                    event.save()


                    return HttpResponseRedirect(reverse("employees:all"))



                    #return HttpResponseRedirect(reverse("employees:all"))

        else:
                            # add form dictionary to context
                    context["form"] = form

                    return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("employees.add_employee")
@login_required
def NonStdBulkUploadEmployee(request):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.resource('s3')

        #add standardization process start
                    #process csv
                    try:
                        print("I am here")
                        #s3.head_object(Bucket='intellidatastatic1', Key='media/employees.csv')
                        obj_to_read1 = s3.Object('intellidatastatic1', 'media/employees-nonstandard-csv.csv')
                        body = obj_to_read1.get()['Body'].read()
                        obj_to_write1 = s3.Object('intellidatastack-s3bucket3-1ezrm28ljj9z9', 'employees/employees-nonstandard-csv.csv')
                        obj_to_write1.put(Body=body)
                        obj_to_read1.delete()
                    except ClientError:
                        print("Or I am here")
                        # Not found
                        print("media/employees-nonstandard-csv.csv key does not exist")

                    #process json
                    try:
                        #s3.head_object(Bucket='intellidatastatic1', Key='media/employers-nonstandard-json.rtf')
                        obj_to_read2 = s3.Object('intellidatastatic1', 'media/employees-nonstandard-json')
                        body = obj_to_read2.get()['Body'].read()
                        obj_to_write2 = s3.Object('intellidatastack-s3bucket3-1ezrm28ljj9z9', 'employees/employees-nonstandard-json')
                        obj_to_write2.put(Body=body)
                        obj_to_read2.delete()
                    except ClientError:
                        # Not found
                        print("media/employees-nonstandard-json key does not exist")

                    #process xml
                    try:
                        #s3.head_object(Bucket='intellidatastatic1', Key='media/employers-nonstandard-json.rtf')
                        obj_to_read2 = s3.Object('intellidatastatic1', 'media/employees-nonstandard-xml')
                        body = obj_to_read2.get()['Body'].read()
                        obj_to_write2 = s3.Object('intellidatastack-s3bucket3-1ezrm28ljj9z9', 'employees/employees-nonstandard-xml')
                        obj_to_write2.put(Body=body)
                        obj_to_read2.delete()
                    except ClientError:
                        # Not found
                        print("media/employees-nonstandard-xml key does not exist")


                    return HttpResponseRedirect(reverse("employees:all"))
        else:
                           # add form dictionary to context
                   context["form"] = form

                   return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("employees.add_employee")
@login_required
def NonStdRefresh(request):
                    #refresh
                    s3 = boto3.client('s3')

                    try:
                        s3.head_object(Bucket='intellidatastatic1', Key='media/employees_nonstd.csv')


                        s3.download_file('intellidatastatic1', 'media/employees_nonstd.csv', 'employees.csv')

                        if os.stat("employees.csv").st_size != 0:

                            with open('employees.csv', 'rt') as csv_file:
                                array_good =[]
                                array_bad = []
                                #array_bad =[]
                                next(csv_file) # skip header line
                                #start here
                                execution_start_time = datetime.now()
                                for row in csv.reader(csv_file):
                                                              bad_ind = 0
                                                              array1=[]
                                                              array2=[]

                                                              #populate serial number
                                                              serial=row[0]
                                                              array2.append(serial)

                                                            #pass employee:
                                                              employeeid=row[1]
                                                              array2.append(employeeid)

                                                              employer=row[30]
                                                              employer_instance=Employer.objects.filter(employerid=employer)[0]
                                                              employer_ident=employer_instance.pk
                                                              pk=employer_ident

                                                              transmission_pk=Employer.objects.get(pk=pk).transmission_id
                                                              transmissionid=Transmission.objects.get(pk=transmission_pk).transmissionid
                                                              sendername=Transmission.objects.get(pk=transmission_pk).SenderName

                                                              if employer == "":
                                                                   bad_ind = 1
                                                                   description = "employer is mandatory"
                                                                   array1.append(serial)
                                                                   array1.append(employeeid)
                                                                   array1.append(name)
                                                                   array1.append(pk)
                                                                   array1.append(description)
                                                                   array1.append(pk)
                                                                   array1.append(Employer.objects.get(pk=pk).employerid)
                                                                   array1.append(transmissionid)
                                                                   array1.append(sendername)
                                                                   array_bad.append(array1)
                                                              else:
                                                                  array2.append(pk)

                                                               #validate name
                                                              name=row[3]
                                                              array1=[]
                                                              if name == "":
                                                                  bad_ind = 1
                                                                  description = "Name is mandatory"
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(name)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)

                                                              else:
                                                                  array2.append(name)

                                                              slug=slugify(row[3])
                                                              #array2.append(slug)

                                                              ssn=row[2]
                                                              if (Mandatory.objects.filter(attributes='employee_ssn').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_ssn')[0].required
                                                                  if (var == "Yes" and ssn ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "SSN is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(ssn)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(ssn)
                                                              else:
                                                                      array2.append(ssn)



                                                              gendercode=row[4]
                                                              if (Mandatory.objects.filter(attributes='employee_gendercode').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_gendercode')[0].required
                                                                  if (var == "Yes" and gendercode ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "Gendercode is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(gendercode)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(gendercode)
                                                              else:
                                                                      array2.append(gendercode)

                                                              #validate age
                                                              age=int(row[5])
                                                              array1=[]
                                                              if age == "":
                                                                  bad_ind=1
                                                                  description = "Age must be numeric "
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(age)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              elif (age <= 0 or age >= 100):
                                                                  bad_ind=1
                                                                  description = "Age must be between 1 and 99 years "
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(age)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              else:
                                                                   array2.append(age)

                                                              birthdate=row[6]
                                                              if (Mandatory.objects.filter(attributes='employee_birthdate').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_birthdate')[0].required
                                                                  if (var == "Yes" and birthdate ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "Birthdate is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(birthdate)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(birthdate)
                                                              else:
                                                                      array2.append(birthdate)

                                                              maritalstatus=row[7]
                                                              if (Mandatory.objects.filter(attributes='employee_maritalstatus').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_maritalstatus')[0].required
                                                                  if (var == "Yes" and maritalstatus ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "Marital status is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(maritalstatus)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(maritalstatus)
                                                              else:
                                                                      array2.append(maritalstatus)

                                                              #validate address line 1
                                                              home_address_line_1=row[8]
                                                              array1=[]
                                                              if home_address_line_1 == "":
                                                                  bad_ind = 1
                                                                  description = "Home address line 1 is mandatory"
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(home_address_line_1)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              else:
                                                                  array2.append(home_address_line_1)


                                                              #validate address line 2
                                                              home_address_line_2=row[9]
                                                              if (Mandatory.objects.filter(attributes='employee_home_address_line_2').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_home_address_line_2')[0].required
                                                                  if (var == "Yes" and home_address_line_2 ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "Home address 2 is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(home_address_line_2)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(home_address_line_2)
                                                              else:
                                                                      array2.append(home_address_line_2)

                                                                   #validate city
                                                              home_city=row[10]
                                                              array1=[]
                                                              if home_city == "":
                                                                   bad_ind = 1
                                                                   description = "Home city is mandatory"
                                                                   array1.append(serial)
                                                                   array1.append(employeeid)
                                                                   array1.append(name)
                                                                   array1.append(home_city)
                                                                   array1.append(description)
                                                                   array1.append(pk)
                                                                   array1.append(Employer.objects.get(pk=pk).employerid)
                                                                   array1.append(transmissionid)
                                                                   array1.append(sendername)
                                                                   array_bad.append(array1)
                                                              else:
                                                                   array2.append(home_city)

                                                                   #validate state
                                                              home_state=row[11]
                                                              array1=[]
                                                              if home_state == "":
                                                                   bad_ind = 1
                                                                   description = "Home state is mandatory"
                                                                   array1.append(serial)
                                                                   array1.append(employeeid)
                                                                   array1.append(name)
                                                                   array1.append(home_state)
                                                                   array1.append(description)
                                                                   array1.append(pk)
                                                                   array1.append(Employer.objects.get(pk=pk).employerid)
                                                                   array1.append(transmissionid)
                                                                   array1.append(sendername)
                                                                   array_bad.append(array1)
                                                              else:
                                                                  array2.append(home_state)

                                                                  #validate zipcode
                                                              home_zipcode=row[12]
                                                              array1=[]
                                                              if home_zipcode == "":
                                                                    bad_ind = 1
                                                                    description = "Zipcode is mandatory"
                                                                    array1.append(serial)
                                                                    array1.append(employeeid)
                                                                    array1.append(name)
                                                                    array1.append(home_zipcode)
                                                                    array1.append(description)
                                                                    array1.append(pk)
                                                                    array1.append(Employer.objects.get(pk=pk).employerid)
                                                                    array1.append(transmissionid)
                                                                    array1.append(sendername)
                                                                    array_bad.append(array1)
                                                              else:
                                                                   array2.append(home_zipcode)

                                                              mail_address_line_1=row[13]
                                                              if (Mandatory.objects.filter(attributes='employee_mail_address_line_1').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_mail_address_line_1')[0].required
                                                                  if (var == "Yes" and mail_address_line_1 ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "Mail_address_line_1 is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(mail_address_line_1)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(mail_address_line_1)
                                                              else:
                                                                      array2.append(mail_address_line_1)

                                                              mail_address_line_2=row[14]
                                                              if (Mandatory.objects.filter(attributes='employee_mail_address_line_2').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_mail_address_line_2')[0].required
                                                                  if (var == "Yes" and mail_address_line_2 ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "mail_address_line_2 is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(mail_address_line_2)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(mail_address_line_2)
                                                              else:
                                                                      array2.append(mail_address_line_2)

                                                              mail_city=row[15]
                                                              if (Mandatory.objects.filter(attributes='employee_mail_city').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_mail_city')[0].required
                                                                  if (var == "Yes" and mail_city ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "mail_city is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(mail_city)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(mail_city)
                                                              else:
                                                                      array2.append(mail_city)

                                                              mail_state=row[16]
                                                              if (Mandatory.objects.filter(attributes='employee_mail_state').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_mail_state')[0].required
                                                                  if (var == "Yes" and mail_state ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "mail_state is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(mail_state)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(mail_state)
                                                              else:
                                                                      array2.append(mail_state)

                                                              mail_zipcode=row[17]
                                                              if (Mandatory.objects.filter(attributes='employee_mail_zipcode').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_mail_zipcode')[0].required
                                                                  if (var == "Yes" and mail_zipcode ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "mail_zipcode is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(mail_zipcode)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(mail_zipcode)
                                                              else:
                                                                      array2.append(mail_zipcode)

                                                              work_address_line_1=row[18]
                                                              if (Mandatory.objects.filter(attributes='employee_work_address_line_1').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_address_line_1')[0].required
                                                                  if (var == "Yes" and work_address_line_1 ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_address_line_1 is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_address_line_1)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_address_line_1)
                                                              else:
                                                                      array2.append(work_address_line_1)

                                                              work_address_line_2=row[19]
                                                              if (Mandatory.objects.filter(attributes='employee_work_address_line_2').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_address_line_2')[0].required
                                                                  if (var == "Yes" and work_address_line_2 ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_address_line_2 is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_address_line_2)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_address_line_2)
                                                              else:
                                                                      array2.append(work_address_line_2)

                                                              work_city=row[20]
                                                              if (Mandatory.objects.filter(attributes='employee_work_city').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_city')[0].required
                                                                  if (var == "Yes" and work_city ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_city is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_city)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_city)
                                                              else:
                                                                      array2.append(work_city)

                                                              work_state=row[21]
                                                              if (Mandatory.objects.filter(attributes='employee_work_state').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_state')[0].required
                                                                  if (var == "Yes" and work_state ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_state is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_state)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_state)
                                                              else:
                                                                      array2.append(work_state)

                                                              work_zipcode=row[22]
                                                              if (Mandatory.objects.filter(attributes='employee_work_zipcode').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_zipcode')[0].required
                                                                  if (var == "Yes" and work_zipcode ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_zipcode is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_zipcode)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_zipcode)
                                                              else:
                                                                      array2.append(work_zipcode)


                                                                    #validate email
                                                              email=row[23]
                                                              array1=[]
                                                              if email == "":
                                                                  bad_ind=1
                                                                  description = "Email is mandatory "
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(email)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              elif not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", email):
                                                                  bad_ind = 1
                                                                  description = "Invalid email"
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(email)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              else:
                                                                  array2.append(email)

                                                              alternate_email=row[24]
                                                              if (Mandatory.objects.filter(attributes='employee_alternate_email').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_alternate_email')[0].required
                                                                  if (var == "Yes" and alternate_email ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "alternate_email is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(alternate_email)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(alternate_email)
                                                              else:
                                                                      array2.append(alternate_email)

                                                              #validate phone
                                                              home_phone=row[25]
                                                              if (Mandatory.objects.filter(attributes='employee_home_phone').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_home_phone')[0].required
                                                                  if (var == "Yes" and home_phone ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "home_phone is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(home_phone)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(home_phone)
                                                              else:
                                                                      array2.append(home_phone)


                                                              work_phone=row[26]
                                                              if (Mandatory.objects.filter(attributes='employee_work_phone').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_work_phone')[0].required
                                                                  if (var == "Yes" and work_phone ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "work_phone is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(work_phone)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(work_phone)
                                                              else:
                                                                      array2.append(work_phone)

                                                              mobile_phone=row[27]
                                                              array1=[]
                                                              p=[]
                                                              p = mobile_phone
                                                              if p.isnumeric() == False:
                                                                  bad_ind=1
                                                                  description = "Mobile phone must be numbers "
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(mobile_phone)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              elif len(p) != (10 and 11):
                                                                  print(len(p))
                                                                  bad_ind=1
                                                                  description = "Length of mobile phone number is not correct "
                                                                  array1.append(serial)
                                                                  array1.append(employeeid)
                                                                  array1.append(name)
                                                                  array1.append(mobile_phone)
                                                                  array1.append(description)
                                                                  array1.append(pk)
                                                                  array1.append(Employer.objects.get(pk=pk).employerid)
                                                                  array1.append(transmissionid)
                                                                  array1.append(sendername)
                                                                  array_bad.append(array1)
                                                              else:
                                                                   array2.append(mobile_phone)


                                                              enrollment_method=row[28]
                                                              if (Mandatory.objects.filter(attributes='employee_enrollment_method').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_enrollment_method')[0].required
                                                                  if (var == "Yes" and enrollment_method ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "enrollment_method is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(enrollment_method)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(enrollment_method)
                                                              else:
                                                                      array2.append(enrollment_method)

                                                              employment_information=row[29]
                                                              if (Mandatory.objects.filter(attributes='employee_employment_information').exists()):
                                                                  var=Mandatory.objects.filter(attributes='employee_employment_information')[0].required
                                                                  if (var == "Yes" and employment_information ==""):
                                                                       array1=[]
                                                                       bad_ind = 1
                                                                       description = "employment_information is mandatory"
                                                                       array1.append(serial)
                                                                       array1.append(employeeid)
                                                                       array1.append(name)
                                                                       array1.append(employment_information)
                                                                       array1.append(description)
                                                                       array1.append(pk)
                                                                       array1.append(Employer.objects.get(pk=pk).employerid)
                                                                       array1.append(transmissionid)
                                                                       array1.append(sendername)
                                                                       array_bad.append(array1)
                                                                  else:
                                                                       array2.append(employment_information)
                                                              else:
                                                                      array2.append(employment_information)


                                                              if bad_ind == 0:
                                                                  array_good.append(array2)



                                # create good file
                            #with open('employees1.csv', 'w', newline='') as clean_file:
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
                                response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees1.csv')
                                s3.upload_fileobj(buff2, 'intellidatastatic1', 'media/employees1.csv')
                                print("Good File Upload Successful")

                            except FileNotFoundError:
                                 print("The good file was not found")

                            except NoCredentialsError:
                                 print("Credentials not available")


                                   # create bad file
                            #with open('employee_error.csv', 'w', newline='') as error_file:
                            #       writer = csv.writer(error_file)
                            #       writer.writerows(array1)

                            buff3 = io.StringIO()

                            writer = csv.writer(buff3, dialect='excel', delimiter=',')
                            writer.writerows(array_bad)

                            buff4 = io.BytesIO(buff3.getvalue().encode())


                                # save bad file to S3
                            try:
                                response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees_error.csv')
                                s3.upload_fileobj(buff4, 'intellidatastatic1', 'media/employees_error.csv')
                                print("Bad File Upload Successful")

                            except FileNotFoundError:
                                print("The bad file was not found")

                            except NoCredentialsError:
                                print("Credentials not available")

                            # load the employee table
                            s3.download_file('intellidatastatic1', 'media/employees1.csv', 'employees1.csv')

                            with open('employees1.csv', 'rt') as csv_file:
                                bulk_mgr = BulkCreateManager(chunk_size=20)
                                notification = Notification()
                                for row in csv.reader(csv_file):
                                    if row[1] == "":
                                        bulk_mgr.add(models.Employee(employeeid = str(uuid.uuid4())[26:36],
                                                                  name=row[3],
                                                                  slug=slugify(row[3]),
                                                                  ssn=row[4],
                                                                  gendercode=row[5],
                                                                  age=int(row[6]),
                                                                  birthdate=row[7],
                                                                  maritalstatus=row[8],
                                                                  home_address_line_1=row[9],
                                                                  home_address_line_2=row[10],
                                                                  home_city=row[11],
                                                                  home_state=row[12],
                                                                  home_zipcode=row[13],
                                                                  mail_address_line_1=row[14],
                                                                  mail_address_line_2=row[15],
                                                                  mail_city=row[16],
                                                                  mail_state=row[17],
                                                                  mail_zipcode=row[18],
                                                                  work_address_line_1=row[19],
                                                                  work_address_line_2=row[20],
                                                                  work_city=row[21],
                                                                  work_state=row[22],
                                                                  work_zipcode=row[23],
                                                                  email=row[24],
                                                                  alternate_email=row[25],
                                                                  home_phone=row[26],
                                                                  work_phone=row[27],
                                                                  mobile_phone=row[28],
                                                                  enrollment_method=row[29],
                                                                  employment_information=row[30],
                                                                  employer=get_object_or_404(models.Employer, pk=row[2]),
                                                                  employerid=(models.Employer.objects.get(pk=row[2]).employerid),
                                                                  creator = request.user,
                                                                  sms="Initial notification sent",
                                                                  emailer="Initial notification sent",
                                                                  source="Non-Standard Feed Bulk Upload",
                                                                  record_status = "Created",
                                                                  bulk_upload_indicator = "Y"
                                                                  ))
                                    else:
                                        bulk_mgr.add(models.Employee(employeeid = row[1],
                                                                  name=row[3],
                                                                  slug=slugify(row[3]),
                                                                  ssn=row[4],
                                                                  gendercode=row[5],
                                                                  age=int(row[6]),
                                                                  birthdate=row[7],
                                                                  maritalstatus=row[8],
                                                                  home_address_line_1=row[9],
                                                                  home_address_line_2=row[10],
                                                                  home_city=row[11],
                                                                  home_state=row[12],
                                                                  home_zipcode=row[13],
                                                                  mail_address_line_1=row[14],
                                                                  mail_address_line_2=row[15],
                                                                  mail_city=row[16],
                                                                  mail_state=row[17],
                                                                  mail_zipcode=row[18],
                                                                  work_address_line_1=row[19],
                                                                  work_address_line_2=row[20],
                                                                  work_city=row[21],
                                                                  work_state=row[22],
                                                                  work_zipcode=row[23],
                                                                  email=row[24],
                                                                  alternate_email=row[25],
                                                                  home_phone=row[26],
                                                                  work_phone=row[27],
                                                                  mobile_phone=row[28],
                                                                  enrollment_method=row[29],
                                                                  employment_information=row[30],
                                                                  employer=get_object_or_404(models.Employer, pk=row[2]),
                                                                  employerid=(models.Employer.objects.get(pk=row[2]).employerid),
                                                                  creator = request.user,
                                                                  sms="Initial notification sent",
                                                                  emailer="Initial notification sent",
                                                                  source="Non-Standard Feed Bulk Upload",
                                                                  record_status = "Created",
                                                                  bulk_upload_indicator = "Y"
                                                                  ))
                                bulk_mgr.done()


                            with open('employees1.csv', 'rt') as csv_file:
                                for ix in csv.reader(csv_file):

                                        #NOTIFY Employee
                                        mobile_phone=ix[28]
                                        subscription_arn = notification.SubscribeEmployeeObj(mobile_phone)

                                        #Log events
                                        event = Event()
                                        event.EventTypeCode = "SUB"
                                        event.EventSubjectId = ""
                                        event.EventSubjectName = mobile_phone
                                        event.EventTypeReason = "Auto subscribed for push notification"
                                        event.source = "Non-Standard Feed Bulk Upload"
                                        event.creator=request.user
                                        event.save()

                                        notification.TextEmployeeObj(subscription_arn)

                                        #Log events
                                        event = Event()
                                        event.EventTypeCode = "SMS"
                                        event.EventSubjectId = ""
                                        event.EventSubjectName = ""
                                        event.EventTypeReason = "Auto push notification sent for the below auto subscription"
                                        event.source = "Non-Standard Feed Bulk Upload"
                                        event.creator=request.user
                                        event.save()

                                        email=ix[24]
                                        notification.EmailEmployeeObj(email)

                                        #Log events
                                        event = Event()
                                        event.EventTypeCode = "EML"
                                        event.EventSubjectId = ""
                                        event.EventSubjectName = email
                                        event.EventTypeReason = "Auto email notification sent"
                                        event.source = "Non-Standard Feed Bulk Upload"
                                        event.creator=request.user
                                        event.save()



                            # load the employee error table
                            s3.download_file('intellidatastatic1', 'media/employees_error.csv', 'employees_error.csv')


                            #Refresh Error table for concerned employer
                            #EmployeeError.objects.filter(employer_id=pk).delete()
                            EmployeeError.objects.all().delete()

                            with open('employees_error.csv', 'rt') as csv_file:
                                bulk_mgr = BulkCreateManager(chunk_size=20)
                                for row1 in csv.reader(csv_file):
                                    #pk = Employer.objects.get(pk=row1[5]).transmission.pk
                                    bulk_mgr.add(models.EmployeeError(serial = row1[0],
                                                                  employeeid=row1[1],
                                                                  name=row1[2],
                                                                  errorfield=row1[3],
                                                                  description=row1[4],
                                                                  employer=get_object_or_404(models.Employer, pk=row1[5]),
                                                                  employerid=row1[6],
                                                                  transmissionid=row1[7],
                                                                  sendername=row1[8],
                                                                  creator = request.user,
                                                                  source="Non-Standard Feed Bulk Upload"
                                                                  ))
                                bulk_mgr.done()

                                if (os.stat("employees_error.csv").st_size != 0):
                                    email_address=Transmission.objects.get(pk=transmission_pk).planadmin_email
                                    if (email_address!="" and email_address!=None):
                                        sender_name=Transmission.objects.get(pk=transmission_pk).SenderName
                                        attached_file = sender_name + "_error"
                                        attachment_file = "employees_error.csv"
                                        notification.EmailPlanAdmin(email_address, attachment_file, attached_file)


                            #Create the aggregate report
                            execution_end_time = datetime.now()
                            duration = (execution_end_time - execution_start_time)

                            error_report = EmployeeErrorAggregate()
                            error_report.employer = get_object_or_404(Employer, pk=pk)

                            error_report.processed_clean=Employee.objects.filter(employer_id=pk).count()
                            error_report.number_of_error_occurences=EmployeeError.objects.filter(employer_id=pk).count()

                            #distinct = EmployeeError.objects.filter(employer_id=pk).values('serial').annotate(serial_count=Count('serial')).filter(serial_count=1)
                            #records = EmployeeError.objects.filter(serial__in=[item['serial'] for item in distinct]).count()
                            #error_report.error=records


                            error_report.total_employees_till_date=(error_report.processed_clean + error_report.number_of_error_occurences)

                            error_report.execution_time_for_this_run=duration

                            with open('employees.csv', 'rt') as csv_file:
                                next(csv_file) # skip header line
                                lines= len(list(csv_file))
                                print(lines)
                                error_report.volume_processed_in_this_run=lines

                            #Refresh Error aggregate table for concerned employer
                            #EmployeeErrorAggregate.objects.filter(employer_id=pk).delete()


                            error_report.save()

                            #Log events
                            event = Event()
                            event.EventTypeCode = "EEB"
                            event.EventSubjectId = "bulkemployees"
                            event.EventSubjectName = "Bulk processing"
                            event.EventTypeReason = "Non-Standard Feed Bulk Upload"
                            event.source = "Web App"
                            event.creator=request.user
                            event.save()
                            #end here
                        response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees_nonstd.csv')

                    except ClientError:
                        # Not found
                        print("media/employers_nonstd.csv does not exist")

                    return HttpResponseRedirect(reverse("employees:all"))


@permission_required("employees.add_employee")
@login_required
def BulkUploadEmployee_deprecated(request, pk, *args, **kwargs):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.client('s3')
                    s3.download_file('intellidatastatic1', 'media/employees1.csv', 'employees1.csv')

                    with open('employees1.csv', 'rt') as csv_file:
                        bulk_mgr = BulkCreateManager(chunk_size=20)
                        for row in csv.reader(csv_file):
                            bulk_mgr.add(models.Employee(employeeid = str(uuid.uuid4())[26:36],
                                                      name=row[1],
                                                      slug=slugify(row[1]),
                                                      age=int(row[2]),
                                                      address_line_1=row[3],
                                                      address_line_2=row[4],
                                                      city=row[5],
                                                      state=row[6],
                                                      zipcode=row[7],
                                                      email=row[8],
                                                      phone=row[9],
                                                      employer=get_object_or_404(models.Employer, pk=pk),
                                                      creator = request.user,
                                                      record_status = "Created",
                                                      bulk_upload_indicator = "Y"
                                                      ))
                        bulk_mgr.done()

                    return HttpResponseRedirect(reverse("employees:all"))

        else:
                            # add form dictionary to context
                    context["form"] = form

                    return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("employees.add_employee")
@login_required
def BulkUploadSOR(request):

    array = Employee.objects.filter(bulk_upload_indicator='Y')
    serializer = EmployeeSerializer(array, many=True)
    json_array = serializer.data

    api = ApiDomains()
    url = api.employee + "/" + "upload"
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
        Employee.objects.filter(bulk_upload_indicator='Y').update(bulk_upload_indicator=" ")

        #Log events
        event = Event()
        event.EventTypeCode = "EEO"
        event.EventSubjectId = "employeeodsupload"
        event.EventSubjectName = "Bulk upload to ODS"
        event.EventTypeReason = "Employees uploaded to ODS in bulk"
        event.source = "Online Transaction"
        event.creator=request.user
        event.save()

        return HttpResponseRedirect(reverse("employees:all"))


class ViewEmployeeErrorList(LoginRequiredMixin, generic.ListView):
    context_object_name = 'employee_error_list'
    model = models.EmployeeError
    template_name = 'employees/employee_error_list.html'

    #form_class = forms.employeeForm

    def get_queryset(self):
    #    return employee.objects.filter(employer=employer_name)
    #    return employee.objects.all
        #return models.employee.objects.prefetch_related('employer')
        return models.EmployeeError.objects.filter(employer_id=self.kwargs['pk'])


class ViewEmployeeErrorFullList(LoginRequiredMixin, generic.ListView):
    context_object_name = 'employee_error_list'
    model = models.EmployeeError
    template_name = 'employees/employee_error_list.html'

    #form_class = forms.employeeForm

    def get_queryset(self):
    #    return employee.objects.filter(employer=employer_name)
    #    return employee.objects.all
        #return models.employee.objects.prefetch_related('employer')
        return models.EmployeeError.objects.all()

#Send for subscription
@permission_required("employees.add_employee")
@login_required
def SubscribeEmployee(request, pk):

    context ={}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:321504535921:intellidata-employee-communication-topic'

    obj = get_object_or_404(Employee, pk = pk)

    form = EmployeeForm(request.POST or None, instance = obj)

    if form.is_valid():
        number = str(form["mobile_phone"]).strip()
        number_array = number.split()
        number = number_array[3]
        number=number.split("=")[1]
        #to_email_address=to_email_address.strip(")
        number=number.replace('"', '')
        print("that is what I see " + number )
        #emailaddr = str(form["email"])

        # Add  Subscribers
        try:
            response = sns.subscribe(
                        TopicArn=topic_arn,
                        Protocol='SMS',
                        Endpoint=number
                       )
        # Display an error if something goes wrong.
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            print("Subscription done!"),
            obj.sms = "Phone Number Subscribed On " + str(datetime.date.today())
        #form.emailer = "Email Notification Sent on " + str(datetime.date.today())
        form.save()

        #Log events
        event = Event()
        event.EventTypeCode = "SUB"
        event.EventSubjectId = ""
        event.EventSubjectName = "Phone number: " + number
        event.EventTypeReason = "Manually subscribed for push notification"
        event.source = "Online Transaction"
        event.creator=request.user
        event.save()

        return HttpResponseRedirect(reverse("employees:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "employees/employee_form.html", context)



@permission_required("employees.add_employee")
@login_required
def TextEmployee(request, pk):

    context = {}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:321504535921:intellidata-employee-communication-topic'

    message = "Enrollment complete"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Employee, pk = pk)

    form = EmployeeForm(request.POST or None, instance = obj)

    if form.is_valid():

        try:
            response=sns.publish(
                        TopicArn=topic_arn,
                        Message=message
                     )

        # Display an error if something goes wrong.
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            print("SMS sent!"),
            obj.sms = "SMS Notification Sent on " + str(datetime.date.today())

        form.save()

        #Log events
        event = Event()
        event.EventTypeCode = "SMS"
        event.EventSubjectId = obj.employeeid
        event.EventSubjectName = obj.name
        event.EventTypeReason = "Manual push notification sent"
        event.source = "Online Transaction"
        event.creator=request.user
        event.save()

        return HttpResponseRedirect(reverse("employees:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "employees/employee_form.html", context)



@permission_required("employees.add_employee")
@login_required
def EmailEmployee(request, pk):

    context = {}

    message = "Start Enrollment"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Employee, pk = pk)

    form = EmployeeForm(request.POST or None, instance = obj)

    if form.is_valid():
        to_email = str(form["email"]).strip()
        to_email_array = to_email.split()
        to_email_value = to_email_array[3]
        to_email_address=to_email_value.split("=")[1]
        #to_email_address=to_email_address.strip(")
        to_email_address=to_email_address.replace('"', '')
        #to_email_address = "'{}'".format(to_email_address)

        #print("what we see is " + to_email_address)
        #to_email = 'svjt78@gmail.com'
        from_email = 'suvojit.dt@gmail.com'
            # Replace sender@example.com with your "From" address.
        # This address must be verified with Amazon SES.

        SENDER = from_email

        # Replace recipient@example.com with a "To" address. If your account
        # is still in the sandbox, this address must be verified.
        RECIPIENT = to_email_address

        # Specify a configuration set. If you do not want to use a configuration
        # set, comment the following variable, and the
        # ConfigurationSetName=CONFIGURATION_SET argument below.
        #CONFIGURATION_SET = "ConfigSet"

        # If necessary, replace us-west-2 with the AWS Region you're using for Amazon SES.
        AWS_REGION = "us-east-1"

        # The subject line for the email.
        SUBJECT = "Enrollment"

        # The email body for recipients with non-HTML email clients.
        BODY_TEXT = ("Start Enrollment\r\n"
                     "Enrollment complete "
                    )

        # The HTML body of the email.
        BODY_HTML = """<html>
        <head></head>
        <body>
          <h1>Start Enrollment</h1>
          <p>This email was sent with
            <a href='https://aws.amazon.com/ses/'>Amazon SES</a> using the
            <a href='https://aws.amazon.com/sdk-for-python/'>
              AWS SDK for Python (Boto)</a>.</p>
        </body>
        </html>
                    """

        # The character encoding for the email.
        CHARSET = "UTF-8"

        # Create a new SES resource and specify a region.
        client = boto3.client('ses',region_name=AWS_REGION)

        # Try to send the email.
        try:
            #Provide the contents of the email.
            response = client.send_email(
                Destination={
                    'ToAddresses': [
                        RECIPIENT,
                    ],
                },
                Message={
                    'Body': {
                        'Html': {
                            'Charset': CHARSET,
                            'Data': BODY_HTML,
                        },
                        'Text': {
                            'Charset': CHARSET,
                            'Data': BODY_TEXT,
                        },
                    },
                    'Subject': {
                        'Charset': CHARSET,
                        'Data': SUBJECT,
                    },
                },
                Source=SENDER,
                # If you are not using a configuration set, comment or delete the
                # following line
                #ConfigurationSetName=CONFIGURATION_SET,
            )
        # Display an error if something goes wrong.
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            print("Email sent! Message ID:"),
            print(response['MessageId'])
            obj.emailer = "Email Notification Sent on " + str(datetime.date.today())

        #form.emailer = "Email Notification Sent on " + str(datetime.date.today())
        form.save()

        #Log events
        event = Event()
        event.EventTypeCode = "EML"
        event.EventSubjectId = ""
        event.EventSubjectName = RECIPIENT
        event.EventTypeReason = "Manual email notification sent"
        event.source = "Online Transaction"
        event.creator=request.user
        event.save()

        return HttpResponseRedirect(reverse("employees:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "employees/employee_form.html", context)


#rest API call
@api_view(['GET', 'POST'])
def EmployeeList(request):

    if request.method == 'GET':
        contacts = Employee.objects.all()
        serializer = EmployeeSerializer(contacts, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = EmployeeSerializer(data=request.data)

        serializer.is_valid(raise_exception=True)
        employee = Employee()
        event = Event()
        s3 = boto3.client('s3')
        bad_ind=0
        array_bad=[]
        array1=[]

        if serializer.data["employeeid"] == '':
            employee.employeeid = str(uuid.uuid4())[26:36]
            event.EventTypeReason = "New employee received via API"
        else:
            employee.employeeid = serializer.data["employeeid"]
            event.EventTypeReason = "Employee added via API"

        #get the most recent employer instance and pk
        employee.employerid=serializer.data["employerid"]
        employer_instance=Employer.objects.filter(employerid=employee.employerid)[0]
        employer_ident=employer_instance.pk
        pk=employer_ident

        if pk == "":
             bad_ind = 1
             description = "employer is mandatory"
             array1.append(employee.employeeid)
             array1.append(employee.name)
             array1.append(pk)
             array1.append(description)
             array1.append(pk)
             array_bad.append(array1)
        else:
            employee.employer = get_object_or_404(Employer, pk=pk)


        employee.name = serializer.data["name"]
        array1=[]
        if employee.name == "":
            bad_ind = 1
            description = "Name is mandatory"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.name)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.slug=slugify(employee.name)

        employee.ssn = serializer.data["ssn"]
        if (Mandatory.objects.filter(attributes='employee_ssn').exists()):
            var=Mandatory.objects.filter(attributes='employee_ssn')[0].required
            if (var == "Yes" and employee.ssn ==""):
                 array1=[]
                 bad_ind = 1
                 description = "SSN is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.ssn)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.gendercode = serializer.data["gendercode"]
        if (Mandatory.objects.filter(attributes='employee_gendercode').exists()):
            var=Mandatory.objects.filter(attributes='employee_gendercode')[0].required
            if (var == "Yes" and employee.gendercode ==""):
                 array1=[]
                 bad_ind = 1
                 description = "Gendercode is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.gendercode)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.age = serializer.data["age"]
        array1=[]
        if employee.age == "":
            bad_ind=1
            description = "Age must be numeric "
            array1.append(employeeid)
            array1.append(employee.name)
            array1.append(employee.age)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)
        elif (employee.age <= 0 or employee.age >= 100):
            bad_ind=1
            description = "Age must be between 1 and 99 years "
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.age)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.birthdate = serializer.data["birthdate"]
        if (Mandatory.objects.filter(attributes='employee_birthdate').exists()):
            var=Mandatory.objects.filter(attributes='employee_birthdate')[0].required
            if (var == "Yes" and employee.birthdate ==""):
                 array1=[]
                 bad_ind = 1
                 description = "Birthdate is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.birthdate)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.maritalstatus = serializer.data["maritalstatus"]
        if (Mandatory.objects.filter(attributes='employee_maritalstatus').exists()):
            var=Mandatory.objects.filter(attributes='employee_maritalstatus')[0].required
            if (var == "Yes" and employee.maritalstatus ==""):
                 array1=[]
                 bad_ind = 1
                 description = "marital status is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.maritalstatus)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.home_address_line_1 = serializer.data["home_address_line_1"]
        array1=[]
        if employee.home_address_line_1 == "":
            bad_ind = 1
            description = "Home address line 1 is mandatory"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.home_address_line_1)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.home_address_line_2 = serializer.data["home_address_line_2"]

        employee.home_city = serializer.data["home_city"]
        array1=[]
        if employee.home_city == "":
            bad_ind = 1
            description = "Home city is mandatory"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.home_city)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.home_state = serializer.data["home_state"]
        array1=[]
        if employee.home_state == "":
            bad_ind = 1
            description = "Home state is mandatory"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.home_state)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.home_zipcode = serializer.data["home_zipcode"]
        array1=[]
        if employee.home_zipcode == "":
            bad_ind = 1
            description = "Zipcode is mandatory"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.zipcode)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.mail_address_line_1 = serializer.data["mail_address_line_1"]
        if (Mandatory.objects.filter(attributes='employee_mail_address_line_1').exists()):
            var=Mandatory.objects.filter(attributes='employee_mail_address_line_1')[0].required
            if (var == "Yes" and employee.mail_address_line_1 ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mail_address_line_1 is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mail_address_line_1)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.mail_address_line_2 = serializer.data["mail_address_line_2"]
        if (Mandatory.objects.filter(attributes='employee_mail_address_line_2').exists()):
            var=Mandatory.objects.filter(attributes='employee_mail_address_line_2')[0].required
            if (var == "Yes" and employee.mail_address_line_2 ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mail_address_line_2 is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mail_address_line_2)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.mail_city = serializer.data["mail_city"]
        if (Mandatory.objects.filter(attributes='employee_mail_city').exists()):
            var=Mandatory.objects.filter(attributes='employee_mail_city')[0].required
            if (var == "Yes" and employee.mail_city ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mail_city is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mail_city)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)


        employee.mail_state = serializer.data["mail_state"]
        if (Mandatory.objects.filter(attributes='employee_mail_state').exists()):
            var=Mandatory.objects.filter(attributes='employee_mail_state')[0].required
            if (var == "Yes" and employee.mail_state ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mail_state is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mail_state)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.mail_zipcode = serializer.data["mail_zipcode"]
        if (Mandatory.objects.filter(attributes='employee_mail_zipcode').exists()):
            var=Mandatory.objects.filter(attributes='employee_mail_zipcode')[0].required
            if (var == "Yes" and employee.mail_zipcode ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mail_zipcode is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mail_zipcode)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)


        employee.work_address_line_1 = serializer.data["work_address_line_1"]
        if (Mandatory.objects.filter(attributes='employee_work_address_line_1').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_address_line_1')[0].required
            if (var == "Yes" and employee.work_address_line_1 ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_address_line_1 is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_address_line_1)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.work_address_line_2 = serializer.data["work_address_line_2"]
        if (Mandatory.objects.filter(attributes='employee_work_address_line_2').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_address_line_2')[0].required
            if (var == "Yes" and employee.work_address_line_2 ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_address_line_2 is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_address_line_2)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.work_city = serializer.data["work_city"]
        if (Mandatory.objects.filter(attributes='employee_work_city').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_city')[0].required
            if (var == "Yes" and employee.work_city ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_city is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_city)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.work_state = serializer.data["work_state"]
        if (Mandatory.objects.filter(attributes='employee_work_state').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_state')[0].required
            if (var == "Yes" and employee.work_state ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_state is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_state)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.work_zipcode = serializer.data["work_zipcode"]
        if (Mandatory.objects.filter(attributes='employee_work_zipcode').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_zipcode')[0].required
            if (var == "Yes" and employee.work_zipcode ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_zipcode is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_zipcode)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.email = serializer.data["email"]
        array1=[]
        if employee.email == "":
            bad_ind=1
            description = "Email is mandatory "
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.email)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)
        elif not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", employee.email):
            bad_ind = 1
            description = "Invalid email"
            array1.append(employee.employeeid)
            array1.append(employee.name)
            array1.append(employee.email)
            array1.append(description)
            array1.append(pk)
            array_bad.append(array1)

        employee.alternate_email = serializer.data["alternate_email"]
        if (Mandatory.objects.filter(attributes='employee_alternate_email').exists()):
            var=Mandatory.objects.filter(attributes='employee_alternate_email')[0].required
            if (var == "Yes" and employee.alternate_email ==""):
                 array1=[]
                 bad_ind = 1
                 description = "alternate_email is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.alternate_email)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.home_phone = serializer.data["home_phone"]
        if (Mandatory.objects.filter(attributes='employee_home_phone').exists()):
            var=Mandatory.objects.filter(attributes='employee_home_phone')[0].required
            if (var == "Yes" and employee.home_phone ==""):
                 array1=[]
                 bad_ind = 1
                 description = "home_phone is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.home_phone)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.work_phone = serializer.data["work_phone"]
        if (Mandatory.objects.filter(attributes='employee_work_phone').exists()):
            var=Mandatory.objects.filter(attributes='employee_work_phone')[0].required
            if (var == "Yes" and employee.work_phone ==""):
                 array1=[]
                 bad_ind = 1
                 description = "work_phone is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.work_phone)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.mobile_phone = serializer.data["mobile_phone"]
        if (Mandatory.objects.filter(attributes='employee_mobile_phone').exists()):
            var=Mandatory.objects.filter(attributes='employee_mobile_phone')[0].required
            if (var == "Yes" and employee.mobile_phone ==""):
                 array1=[]
                 bad_ind = 1
                 description = "mobile_phone is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.mobile_phone)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.enrollment_method = serializer.data["enrollment_method"]
        if (Mandatory.objects.filter(attributes='employee_enrollment_method').exists()):
            var=Mandatory.objects.filter(attributes='employee_enrollment_method')[0].required
            if (var == "Yes" and employee.enrollment_method ==""):
                 array1=[]
                 bad_ind = 1
                 description = "enrollment_method is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.enrollment_method)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.employment_information = serializer.data["employment_information"]
        if (Mandatory.objects.filter(attributes='employee_employment_information').exists()):
            var=Mandatory.objects.filter(attributes='employee_employment_information')[0].required
            if (var == "Yes" and employee.employment_information ==""):
                 array1=[]
                 bad_ind = 1
                 description = "employment_information is mandatory"
                 array1.append(employee.employeeid)
                 array1.append(employee.name)
                 array1.append(employee.employment_information)
                 array1.append(description)
                 array1.append(pk)
                 array_bad.append(array1)

        employee.source = "Post API"

        employee.creator = get_object_or_404(User, pk=serializer.data["creator"])
        #transmission.create_date = serializer.data["create_date"]
        employee.backend_SOR_connection = "Disconnected"
        employee.response = ""
        employee.commit_indicator = "Not Committed"
        employee.record_status = ""
        employee.bulk_upload_indicator = "Y"
        print("array_bad is ")
        print(array_bad)
        print("employer pk is " + str(pk))

        if bad_ind==1:
            buff3 = io.StringIO()

            writer = csv.writer(buff3, dialect='excel', delimiter=',')
            writer.writerows(array_bad)

            buff4 = io.BytesIO(buff3.getvalue().encode())


                # save bad file to S3
            try:
                response = s3.delete_object(Bucket='intellidatastatic1', Key='media/employees_api_error.csv')
                s3.upload_fileobj(buff4, 'intellidatastatic1', 'media/employees_api_error.csv')
                print("Bad File Upload Successful")

            except FileNotFoundError:
                print("The bad file was not found")

            except NoCredentialsError:
                print("Credentials not available")

            # load the employee error table
            s3.download_file('intellidatastatic1', 'media/employees_api_error.csv', 'employees_api_error.csv')

            #Refresh Error table for concerned employer
            EmployeeError.objects.filter(employer_id=pk).delete()

            with open('employees_api_error.csv', 'rt') as csv_file:
                    bulk_mgr = BulkCreateManager(chunk_size=20)
                    for row1 in csv.reader(csv_file):
                        bulk_mgr.add(models.EmployeeError(serial=0,
                                                  employeeid=row1[0],
                                                  name=row1[1],
                                                  errorfield=row1[2],
                                                  description=row1[3],
                                                  employer=get_object_or_404(models.Employer, pk=pk),
                                                  creator = get_object_or_404(User, pk=serializer.data["creator"]),
                                                  source="Post API"
                                                  ))
                    bulk_mgr.done()

            error_response = EmployeeError.objects.filter(employer_id=pk)
            #error_response = EmployeeError.objects.all()
            print(error_response)
            serializer = EmployeeErrorSerializer(error_response, many=True)
            return Response(serializer.data)

        else:
            #Log events

            event.EventTypeCode = "EEW"
            event.EventSubjectId = employee.employeeid
            event.EventSubjectName = employee.name
            event.source = "Post API"
            event.creator=employee.creator
            event.save()

            employee.save()

            #Notifications
            notification = Notification()
            subscription_arn = notification.SubscribeEmployeeObj(employee.mobile_phone)

            #Log events
            event = Event()
            event.EventTypeCode = "SUB"
            event.EventSubjectId = ""
            event.EventSubjectName = employee.mobile_phone
            event.EventTypeReason = "Auto subscribed for push notification"
            event.source = "Post API"
            event.creator=employee.creator
            event.save()

            notification.TextEmployeeObj(subscription_arn)

            #Log events
            event = Event()
            event.EventTypeCode = "SMS"
            event.EventSubjectId = ""
            event.EventSubjectName = ""
            event.EventTypeReason = "Auto push notification sent for the below auto subscription"
            event.source = "Post API"
            event.creator=employee.creator
            event.save()


            notification.EmailEmployeeObj(employee.email)

            #Log events
            event = Event()
            event.EventTypeCode = "EML"
            event.EventSubjectId = ""
            event.EventSubjectName = employee.email
            event.EventTypeReason = "Auto email notification sent"
            event.source = "Post API"
            event.creator=employee.creator
            event.save()

            return Response(serializer.data)

    #if serializer.is_valid():
    #    serializer.save()

    #    return Response(serializer.data, status=status.HTTP_201_CREATED)

    #    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



#rest API call
@api_view(['GET', 'POST'])
def EmployeeListByEmployer(request, pk):

    if request.method == 'GET':
        contacts = Employee.objects.filter(employer_id = pk)
        serializer = EmployeeSerializer(contacts, many=True)
        return Response(serializer.data)

#notify employees in email and text message on phone

#publish message

@permission_required("employees.add_employee")
@login_required
def Notifyemployee_deprecated(request, pk):

    context = {}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:215632354817:intellidata_notify_topic'

    message = "Start Enrollment"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Employee, pk = pk)

    form = EmployeeForm(request.POST or None, instance = obj)

    if form.is_valid():
        number = str(form["phone"])
        email = str(form["email"])

        sns.subscribe(
                TopicArn=topic_arn,
                Protocol='Email-JSON',
                Endpoint="svjt78@gmail.com"
        )

        sns.publish(
            TopicArn=topic_arn,
            Message=messageJSON
        )

    #number = '+17702233322'
    #sns.publish(PhoneNumber = number, Message='example text message' )

    # Add SMS Subscribers


        form["sms"] = "SMS Notification Sent on " + str(datetime.date.today())
        form["emailer"] = "Email Notification Sent on " + str(datetime.date.today())
        form.save()
        return HttpResponseRedirect(reverse("employees:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "employees/employee_form.html", context)


#class for handling built-in API errors
class APIError(Exception):
    """An API Error Exception"""

    def __init__(self, status):
        self.status = status

    def __str__(self):
        return "APIError: status={}".format(self.status)


def ExportEmployeeDataToCSV(request):
    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="employees.csv"'

    writer = csv.writer(response)

    writer.writerow(['Serial#', 'Employeeid', 'SSN', 'Name', 'Slug', 'Gendercode', 'Age', 'Birthdate', 'Marital_status',
                     'Home_address_line_1', 'Home_address_line_2', 'Home_city', 'Home_state', 'Home_zipcode', 'Mail_address_line_1', 'Mail_address_line_2', 'Mail_city', 'Mail_state', 'Mail_zipcode',
                     'Work_address_line_1', 'Work_address_line_2', 'Work_city', 'Work_state', 'Work_zipcode', 'Email', 'Alternate_email', 'Home_phone', 'Work_phone', 'Mobile_phone', 'Enrollment_method', 'Employment_information',
                     'Employer_name', 'Employer_id', 'Creator', 'Create_Date', 'SMS', 'Emailer', 'Source',
                     'Backend_SOR_connection', 'Commit_indicator', 'Record_status', 'Response', 'Bulk_upload_indicator'])
    #writer.writerow(['Second row', 'A', 'B', 'C', '"Testing"', "Here's a quote"])
    queryset=Employee.objects.all().order_by('-employee_date')
    n=0
    for obj in queryset:
        n=n+1
        writer.writerow([
            smart_str(str(n)),
            smart_str(obj.employeeid),
            smart_str(obj.ssn),
            smart_str(obj.name),
            smart_str(obj.slug),
            smart_str(obj.gendercode),
            smart_str(obj.age),
            smart_str(obj.birthdate),
            smart_str(obj.maritalstatus),
            smart_str(obj.home_address_line_1),
            smart_str(obj.home_address_line_2),
            smart_str(obj.home_city),
            smart_str(obj.home_state),
            smart_str(obj.home_zipcode),
            smart_str(obj.mail_address_line_1),
            smart_str(obj.mail_address_line_2),
            smart_str(obj.mail_city),
            smart_str(obj.mail_state),
            smart_str(obj.mail_zipcode),
            smart_str(obj.work_address_line_1),
            smart_str(obj.work_address_line_2),
            smart_str(obj.work_city),
            smart_str(obj.work_state),
            smart_str(obj.work_zipcode),
            smart_str(obj.email),
            smart_str(obj.alternate_email),
            smart_str(obj.home_phone),
            smart_str(obj.work_phone),
            smart_str(obj.mobile_phone),
            smart_str(obj.enrollment_method),
            smart_str(obj.employment_information),
            smart_str(obj.employer),
            smart_str(obj.employerid),
            smart_str(obj.creator),
            smart_str(obj.employee_date),
            smart_str(obj.sms),
            smart_str(obj.emailer),
            smart_str(obj.source),
            smart_str(obj.backend_SOR_connection),
            smart_str(obj.commit_indicator),
            smart_str(obj.record_status),
            smart_str(obj.response),
            smart_str(obj.bulk_upload_indicator)
        ])

    return response
