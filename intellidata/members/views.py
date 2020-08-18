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
from groups.models import Group
from members.models import Member
from members.models import MemberError
from members.models import MemberErrorAggregate
from . import models
from . import forms
from members.forms import MemberForm
from bulkuploads.models import BulkUpload
from bulkuploads.forms import BulkUploadForm
import boto3
from botocore.exceptions import ClientError
import json
import csv
from groups.utils import BulkCreateManager
import os.path
from os import path
from django.utils.text import slugify
import misaka
import uuid
from groups.utils import ApiDomains
from apicodes.models import APICodes
from groups.utils import Notification
import requests
from django.contrib.auth.models import User
import re
from botocore.exceptions import NoCredentialsError
import io
from django.db.models import Count

# For Rest rest_framework
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from members.serializers import MemberSerializer


class SingleMember(LoginRequiredMixin, generic.DetailView):
    context_object_name = 'member_details'
    model = models.Member
    template_name = 'members/member_detail.html'
    #form_class = forms.MemberForm

class ListMembers(LoginRequiredMixin, generic.ListView):
    context_object_name = 'member_list'
    model = models.Member
    template_name = 'members/member_list.html'

    #form_class = forms.MemberForm

    def get_queryset(self):
    #    return Member.objects.filter(group=group_name)
    #    return Member.objects.all
        return models.Member.objects.prefetch_related('group')


class CreateMember(LoginRequiredMixin, PermissionRequiredMixin, generic.CreateView):
    #fields = ("name", "age")
    permission_required = 'members.add_member'
    template_name = 'members/member_form.html'
    context_object_name = 'member_details'
    redirect_field_name = 'members/member_detail.html'
    model = models.Member
    form_class = forms.MemberForm

    def dispatch(self, request, *args, **kwargs):
        """
        Overridden so we can make sure the `Group` instance exists
        before going any further.
        """
        self.group = get_object_or_404(models.Group, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):

        if not self.request.user.has_perm('members.add_member'):
            raise HttpResponseForbidden()
        else:
            """
            Overridden to add the group relation to the `Member` instance.
            """
            form.instance.group = self.group
            form.instance.creator = self.request.user
            form.instance.record_status = "Created"

            email_addr = form.instance.email
            phone_num = form.instance.phone
            print(phone_num)

            #NOTIFY MEMBER
            notification = Notification()
            subscription_arn = notification.SubscribeMemberObj(phone_num)
            notification.TextMemberObj(subscription_arn)

            notification.EmailMemberObj(email_addr)

            form.instance.sms = "Initial notification sent"
            form.instance.emailer = "Initial notification sent"

            return super().form_valid(form)

#Pull from  backend system of record(SOR)
@permission_required("members.add_member")
@login_required
def BackendPull(request, pk):
        # fetch the object related to passed id

        member_obj = get_object_or_404(Member, pk = pk)

        api = ApiDomains()
        url = api.member + "/" + "latest"
        payload={'ident': member_obj.memberid}
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
            obj.memberid = json_data["MEMBER_ID"]
            obj.name = json_data["NAME"]
            obj.name_html = misaka.html(obj.name)
            obj.age = json_data["AGE"]

            obj.address_line_1 = json_data["ADDRESS_LINE_1"]
            obj.ADDRESS_LINE_2 = json_data["ADDRESS_LINE_2"]
            obj.city = json_data["CITY"]
            obj.state = json_data["STATE"]
            obj.zipcode = json_data["ZIPCODE"]


            obj.email = json_data["EMAIL"]
            obj.phone = json_data["PHONE"]

            group_id = json_data["GROUP"]
            group_obj = get_object_or_404(Group, pk = group_id)
            obj.group = group_obj.name

            obj.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            obj.member_date = json_data["MEMBER_DATE"]

            obj.sms = json_data["SMS"]
            obj.emailer = json_data["EMAILER"]
            obj.artefact = json_data["ARTEFACT"]

            obj.backend_SOR_connection = json_data["CONNECTION"]
            obj.response = json_data["RESPONSE"]
            obj.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj.record_status = json_data["RECORD_STATUS"]

            context = {'member_details':obj}

            return render(request, "members/member_detail.html", context=context)



#Pull from  backend system of record(SOR)
@permission_required("members.add_member")
@login_required
def ListMembersHistory(request, pk):

                context ={}

                member_obj = get_object_or_404(Member, pk = pk)

                api = ApiDomains()
                url = api.member + "/" + "history"

                payload={'ident': member_obj.memberid}

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
                     obj = Member()
                      #dict_data.append(json.loads(json_data[ix]))
                     obj.pk = int(json_data[ix]["LOCAL_ID"])
                     obj.memberid = json_data[ix]["MEMBER_ID"]
                     obj.name = json_data[ix]["NAME"]
                     obj.name_html = misaka.html(obj.name)
                     obj.age = json_data[ix]["AGE"]

                     obj.address_line_1 = json_data[ix]["ADDRESS_LINE_1"]
                     obj.ADDRESS_LINE_2 = json_data[ix]["ADDRESS_LINE_2"]
                     obj.city = json_data[ix]["CITY"]
                     obj.state = json_data[ix]["STATE"]
                     obj.zipcode = json_data[ix]["ZIPCODE"]

                     obj.email = json_data[ix]["EMAIL"]
                     obj.phone = json_data[ix]["PHONE"]

                     group_id = json_data[ix]["GROUP"]
                     group_obj = get_object_or_404(Group, pk = group_id)
                     obj.group = group_obj

                     obj.creator = User.objects.get(pk=int(json_data[ix]["CREATOR"]))
                     obj.member_date = json_data[ix]["MEMBER_DATE"]

                     obj.sms = json_data[ix]["SMS"]
                     obj.emailer = json_data[ix]["EMAILER"]
                     obj.artefact = json_data[ix]["ARTEFACT"]

                     obj.backend_SOR_connection = json_data[ix]["CONNECTION"]
                     obj.response = json_data[ix]["RESPONSE"]
                     obj.commit_indicator = json_data[ix]["COMMIT_INDICATOR"]
                     obj.record_status = json_data[ix]["RECORD_STATUS"]

                     obj_data.append(obj)

                    context = {'object_list':obj_data}

                    return render(request, "members/member_list.html", context=context)

                    #mesg_obj = get_object_or_404(APICodes, http_response_code = 1000)
                    #status_message=mesg_obj.http_response_message
                    #mesg="1000" + " - " + status_message
                    # add form dictionary to context
                    #message={'messages':mesg}
                    #return render(request, "messages.html", context=message)


@permission_required("members.add_member")
@login_required
def RefreshMember(request, pk):
        # fetch the object related to passed id
        context ={}
        member_obj = get_object_or_404(Member, pk = pk)

        api = ApiDomains()
        url = api.member + "/" + "refresh"

        payload={'ident': member_obj.memberid}

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
            obj1=Member()

            #OVERRIDE THE OBJECT WITH API data
            obj1.pk = int(json_data["LOCAL_ID"])
            obj1.memberid = json_data["MEMBER_ID"]
            obj1.name = json_data["NAME"]
            obj1.name_html = misaka.html(obj1.name)
            obj1.age = json_data["AGE"]

            obj1.address_line_1 = json_data["ADDRESS_LINE_1"]
            obj1.address_line_2 = json_data["ADDRESS_LINE_2"]
            obj1.city = json_data["CITY"]
            obj1.state = json_data["STATE"]
            obj1.zipcode = json_data["ZIPCODE"]

            obj1.email = json_data["EMAIL"]
            obj1.phone = json_data["PHONE"]

            group_id = json_data["GROUP"]
            group_obj = get_object_or_404(Group, pk = group_id)
            obj1.group = group_obj

            obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
            obj1.member_date = json_data["MEMBER_DATE"]

            obj1.sms = json_data["SMS"]
            obj1.emailer = json_data["EMAILER"]
            obj1.artefact = json_data["ARTEFACT"]

            obj1.backend_SOR_connection = json_data["CONNECTION"]
            obj1.response = json_data["RESPONSE"]
            obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
            obj1.record_status = json_data["RECORD_STATUS"]

            obj1.save()

            context = {'member_details':obj1}

            return render(request, "members/member_detail.html", context=context)



@login_required
@permission_required("members.add_member")
def VersionMember(request, pk):
    # dictionary for initial data with
    # field names as keys
    context ={}

    # fetch the object related to passed id
    obj = get_object_or_404(Member, pk = pk)

    # pass the object as instance in form
    form = MemberForm(request.POST or None, instance = obj)

    # save the data from the form and
    # redirect to detail_view
    if form.is_valid():
            obj.pk = int(round(time.time() * 1000))
            form.instance.creator = request.user
            form.save()
            return HttpResponseRedirect(reverse("members:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "members/member_form.html", context)


class UpdateMember(LoginRequiredMixin, PermissionRequiredMixin, generic.UpdateView):
    #fields = ("name", "age")
    permission_required = 'members.change_member'
    template_name = 'members/member_form.html'
    #context_object_name = 'member_details'
    redirect_field_name = 'members/member_detail.html'
    model = models.Member
    form_class = forms.MemberForm

    def form_valid(self, form):

        if not self.request.user.has_perm('members.change_member'):
            raise HttpResponseForbidden()
        else:
            form.instance.creator = self.request.user
            form.instance.record_status = "Updated"
            return super().form_valid(form)


class DeleteMember(LoginRequiredMixin, PermissionRequiredMixin, generic.DeleteView,):
    permission_required = 'members.delete_member'
    context_object_name = 'member_details'
    form_class = forms.MemberForm
    model = models.Member
    template_name = 'members/member_delete_confirm.html'
    success_url = reverse_lazy("members:all")


    def delete(self, *args, **kwargs):
        messages.success(self.request, "Member Deleted")
        return super().delete(*args, **kwargs)

    def form_valid(self, form):

        if not self.request.user.has_perm('members.delete_member'):
            raise HttpResponseForbidden()
        else:
            return super().form_valid(form)


def SearchMembersForm(request):
    return render(request,'members/member_search_form.html')


class SearchMembersList(LoginRequiredMixin, generic.ListView):
    login_url = '/login/'
    model = models.Member
    template_name = 'members/member_search_list.html'

    def get_queryset(self, **kwargs): # new
        query = self.request.GET.get('q', None)
        object_list = models.Member.objects.filter(
            Q(name__icontains=query) | Q(age__icontains=query)
        )

        #change start for remote SearchMembersForm
        if not object_list:
            api = ApiDomains()
            url = api.member + "/" + "refresh"

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
                obj1=Member()

                #OVERRIDE THE OBJECT WITH API data
                obj1.pk = int(json_data["LOCAL_ID"])
                obj1.memberid = json_data["MEMBER_ID"]
                obj1.name = json_data["NAME"]
                obj1.name_html = misaka.html(obj.name)
                obj1.age = json_data["AGE"]
                obj1.email = json_data["EMAIL"]
                obj1.phone = json_data["PHONE"]

                obj1.address_line_1 = json_data["ADDRESS_LINE_1"]
                obj1.ADDRESS_LINE_2 = json_data["ADDRESS_LINE_2"]
                obj1.city = json_data["CITY"]
                obj1.state = json_data["STATE"]
                obj1.zipcode = json_data["ZIPCODE"]

                obj1.group = json_data["GROUP"]
                obj1.creator = User.objects.get(pk=int(json_data["CREATOR"]))
                obj1.member_date = json_data["MEMBER_DATE"]

                obj1.sms = json_data["SMS"]
                obj1.emailer = json_data["EMAILER"]
                obj1.artefact = json_data["ARTEFACT"]

                obj1.backend_SOR_connection = json_data["CONNECTION"]
                obj1.response = json_data["RESPONSE"]
                obj1.commit_indicator = json_data["COMMIT_INDICATOR"]
                obj1.record_status = json_data["RECORD_STATUS"]

                obj1.save()

                object_remote_list = Member.objects.filter(memberid=query)
                print(object_remote_list)
                return object_remote_list

        else:
        #change end for remote SearchMembersForm

                return object_list


@permission_required("members.add_member")
@login_required
def BulkUploadMember(request, pk, *args, **kwargs):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.client('s3')
                    s3.download_file('intellidatastatic', 'media/members.csv', 'members.csv')

                    with open('members.csv', 'rt') as csv_file:
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

                                                    #pass member:
                                                      memberid=row[1]
                                                      array2.append(memberid)
                                                       #validate name
                                                      name=row[2]
                                                      if name == "":
                                                          bad_ind = 1
                                                          description = "Name is mandatory"
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(name)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)

                                                      else:
                                                          array2.append(name)

                                                      slug=slugify(row[2])
                                                      #array2.append(slug)

                                                      #validate age
                                                      age=int(row[3])
                                                      array1=[]
                                                      if age == "":
                                                          bad_ind=1
                                                          description = "Age must be numeric "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(age)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      elif (age <= 0 or age >= 100):
                                                          bad_ind=1
                                                          description = "Age must be between 1 and 99 years "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(age)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      else:
                                                           array2.append(age)

                                                      #validate address line 1
                                                      address_line_1=row[4]
                                                      array1=[]
                                                      if address_line_1 == "":
                                                          bad_ind = 1
                                                          description = "Address line 1 is mandatory"
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(address_line_1)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      else:
                                                          array2.append(address_line_1)


                                                      #validate address line 2
                                                      address_line_2=row[5]
                                                      array2.append(address_line_2)

                                                           #validate city
                                                      city=row[6]
                                                      array1=[]
                                                      if city == "":
                                                           bad_ind = 1
                                                           description = "City is mandatory"
                                                           array1.append(serial)
                                                           array1.append(name)
                                                           array1.append(city)
                                                           array1.append(description)
                                                           array1.append(pk)
                                                           array_bad.append(array1)
                                                      else:
                                                           array2.append(city)

                                                           #validate state
                                                      state=row[7]
                                                      array1=[]
                                                      if state == "":
                                                           bad_ind = 1
                                                           description = "State is mandatory"
                                                           array1.append(serial)
                                                           array1.append(name)
                                                           array1.append(state)
                                                           array1.append(description)
                                                           array1.append(pk)
                                                           array_bad.append(array1)
                                                      else:
                                                          array2.append(state)

                                                          #validate zipcode
                                                      zipcode=row[8]
                                                      array1=[]
                                                      if zipcode == "":
                                                            bad_ind = 1
                                                            description = "Zipcode is mandatory"
                                                            array1.append(serial)
                                                            array1.append(name)
                                                            array1.append(zipcode)
                                                            array1.append(description)
                                                            array1.append(pk)
                                                            array_bad.append(array1)
                                                      else:
                                                           array2.append(zipcode)

                                                            #validate email
                                                      email=row[9]
                                                      array1=[]
                                                      if email == "":
                                                          bad_ind=1
                                                          description = "Email is mandatory "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(email)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      elif not re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", email):
                                                          bad_ind = 1
                                                          description = "Invalid email"
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(email)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      else:
                                                          array2.append(email)

                                                      #validate phone
                                                      phone=row[10]
                                                      array1=[]
                                                      p=[]
                                                      p = phone
                                                      l=len(p)
                                                      p1 = p[0]
                                                      p2=p[1:l]
                                                      if phone == "":
                                                          bad_ind=1
                                                          description = "Phone is mandatory "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(phone)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      #elif p1 != "+":
                                                          #bad_ind=1
                                                          #description = "Phone is not in right format "
                                                          #array1.append(description)
                                                      elif p.isnumeric() == False:
                                                          bad_ind=1
                                                          description = "Phone must be numbers "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(phone)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      elif len(p) != (10 and 11):
                                                          print(len(p))
                                                          bad_ind=1
                                                          description = "Length of phone number is not correct "
                                                          array1.append(serial)
                                                          array1.append(name)
                                                          array1.append(phone)
                                                          array1.append(description)
                                                          array1.append(pk)
                                                          array_bad.append(array1)
                                                      else:
                                                           array2.append(phone)


                                                      if bad_ind == 0:
                                                          array_good.append(array2)



                        # create good file
                    #with open('members1.csv', 'w', newline='') as clean_file:
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
                        response = s3.delete_object(Bucket='intellidatastatic', Key='media/members1.csv')
                        s3.upload_fileobj(buff2, 'intellidatastatic', 'media/members1.csv')
                        print("Good File Upload Successful")

                    except FileNotFoundError:
                         print("The good file was not found")

                    except NoCredentialsError:
                         print("Credentials not available")


                           # create bad file
                    #with open('member_error.csv', 'w', newline='') as error_file:
                    #       writer = csv.writer(error_file)
                    #       writer.writerows(array1)

                    buff3 = io.StringIO()

                    writer = csv.writer(buff3, dialect='excel', delimiter=',')
                    writer.writerows(array_bad)

                    buff4 = io.BytesIO(buff3.getvalue().encode())


                        # save bad file to S3
                    try:
                        response = s3.delete_object(Bucket='intellidatastatic', Key='media/members_error.csv')
                        s3.upload_fileobj(buff4, 'intellidatastatic', 'media/members_error.csv')
                        print("Bad File Upload Successful")

                    except FileNotFoundError:
                        print("The bad file was not found")

                    except NoCredentialsError:
                        print("Credentials not available")

                    # load the member table
                    s3.download_file('intellidatastatic', 'media/members1.csv', 'members1.csv')

                    with open('members1.csv', 'rt') as csv_file:
                        bulk_mgr = BulkCreateManager(chunk_size=20)
                        notification = Notification()
                        for row in csv.reader(csv_file):
                            if row[1] == "":
                                bulk_mgr.add(models.Member(memberid = str(uuid.uuid4())[26:36],
                                                          name=row[2],
                                                          slug=slugify(row[2]),
                                                          age=int(row[3]),
                                                          address_line_1=row[4],
                                                          address_line_2=row[5],
                                                          city=row[6],
                                                          state=row[7],
                                                          zipcode=row[8],
                                                          email=row[9],
                                                          phone=row[10],
                                                          group=get_object_or_404(models.Group, pk=pk),
                                                          creator = request.user,
                                                          sms="Initial notification sent",
                                                          emailer="Initial notification sent",
                                                          record_status = "Created",
                                                          bulk_upload_indicator = "Y"
                                                          ))
                            else:
                                bulk_mgr.add(models.Member(memberid = row[1],
                                                          name=row[2],
                                                          slug=slugify(row[2]),
                                                          age=int(row[3]),
                                                          address_line_1=row[4],
                                                          address_line_2=row[5],
                                                          city=row[6],
                                                          state=row[7],
                                                          zipcode=row[8],
                                                          email=row[9],
                                                          phone=row[10],
                                                          group=get_object_or_404(models.Group, pk=pk),
                                                          creator = request.user,
                                                          sms="Initial notification sent",
                                                          emailer="Initial notification sent",
                                                          record_status = "Created",
                                                          bulk_upload_indicator = "Y"
                                                          ))

                    with open('members1.csv', 'rt') as csv_file:
                        for ix in csv.reader(csv_file):

                                #NOTIFY MEMBER
                                subscription_arn = notification.SubscribeMemberObj(ix[10])
                                notification.TextMemberObj(subscription_arn)

                                notification.EmailMemberObj(ix[9])

                        bulk_mgr.done()

                        # load the member error table
                        s3.download_file('intellidatastatic', 'media/members_error.csv', 'members_error.csv')

                        #Refresh Error table for concerned group
                        MemberError.objects.filter(group_id=pk).delete()

                        with open('members_error.csv', 'rt') as csv_file:
                            bulk_mgr = BulkCreateManager(chunk_size=20)
                            for row1 in csv.reader(csv_file):
                                bulk_mgr.add(models.MemberError(serial = row1[0],
                                                          memberid=row1[1],
                                                          name=row1[2],
                                                          errorfield=row1[3],
                                                          description=row1[4],
                                                          group=get_object_or_404(models.Group, pk=pk),
                                                          creator = request.user,
                                                          source = ""
                                                          ))
                            bulk_mgr.done()


                    error_report = MemberErrorAggregate()
                    error_report.group = get_object_or_404(Group, pk=pk)

                    error_report.clean=Member.objects.filter(group_id=pk).count()
                    error_report.error=MemberError.objects.filter(group_id=pk).count()

                    #distinct = MemberError.objects.filter(group_id=pk).values('serial').annotate(serial_count=Count('serial')).filter(serial_count=1)
                    #records = MemberError.objects.filter(serial__in=[item['serial'] for item in distinct]).count()
                    #error_report.error=records


                    error_report.total=(error_report.clean + error_report.error)

                    #Refresh Error aggregate table for concerned group
                    MemberErrorAggregate.objects.filter(group_id=pk).delete()

                    error_report.save()



                    return HttpResponseRedirect(reverse("members:all"))



                    #return HttpResponseRedirect(reverse("members:all"))

        else:
                            # add form dictionary to context
                    context["form"] = form

                    return render(request, "bulkuploads/bulkupload_form.html", context)



@permission_required("members.add_member")
@login_required
def BulkUploadMember_deprecated(request, pk, *args, **kwargs):

        context ={}

        form = BulkUploadForm(request.POST, request.FILES)

        if form.is_valid():
                    form.instance.creator = request.user
                    form.save()

                    s3 = boto3.client('s3')
                    s3.download_file('intellidatastatic', 'media/members1.csv', 'members1.csv')

                    with open('members1.csv', 'rt') as csv_file:
                        bulk_mgr = BulkCreateManager(chunk_size=20)
                        for row in csv.reader(csv_file):
                            bulk_mgr.add(models.Member(memberid = str(uuid.uuid4())[26:36],
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
                                                      group=get_object_or_404(models.Group, pk=pk),
                                                      creator = request.user,
                                                      record_status = "Created",
                                                      bulk_upload_indicator = "Y"
                                                      ))
                        bulk_mgr.done()

                    return HttpResponseRedirect(reverse("members:all"))

        else:
                            # add form dictionary to context
                    context["form"] = form

                    return render(request, "bulkuploads/bulkupload_form.html", context)


@permission_required("members.add_member")
@login_required
def BulkUploadSOR(request):

    array = Member.objects.filter(bulk_upload_indicator='Y')
    serializer = MemberSerializer(array, many=True)
    json_array = serializer.data

    api = ApiDomains()
    url = api.member + "/" + "upload"
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
        Member.objects.filter(bulk_upload_indicator='Y').update(bulk_upload_indicator=" ")
        return HttpResponseRedirect(reverse("members:all"))


class ViewMemberErrorList(LoginRequiredMixin, generic.ListView):
    context_object_name = 'member_error_list'
    model = models.MemberError
    template_name = 'members/member_error_list.html'

    #form_class = forms.MemberForm

    def get_queryset(self):
    #    return Member.objects.filter(group=group_name)
    #    return Member.objects.all
        #return models.Member.objects.prefetch_related('group')
        return models.MemberError.objects.filter(group_id=self.kwargs['pk'])



#Send for subscription
@permission_required("members.add_member")
@login_required
def SubscribeMember(request, pk):

    context ={}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:215632354817:intellidata_notify_topic'

    obj = get_object_or_404(Member, pk = pk)

    form = MemberForm(request.POST or None, instance = obj)

    if form.is_valid():
        number = str(form["phone"]).strip()
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
        return HttpResponseRedirect(reverse("members:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "members/member_form.html", context)



@permission_required("members.add_member")
@login_required
def TextMember(request, pk):

    context = {}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:215632354817:intellidata_notify_topic'

    message = "Start Enrollment using http://www.google.com"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Member, pk = pk)

    form = MemberForm(request.POST or None, instance = obj)

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
        return HttpResponseRedirect(reverse("members:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "members/member_form.html", context)



@permission_required("members.add_member")
@login_required
def EmailMember(request, pk):

    context = {}

    message = "Start Enrollment"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Member, pk = pk)

    form = MemberForm(request.POST or None, instance = obj)

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
                     "You are being requested to start "
                     "Enrollemnt"
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
        return HttpResponseRedirect(reverse("members:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "members/member_form.html", context)


#rest API call
@api_view(['GET', 'POST'])
def MemberList(request):

    if request.method == 'GET':
        contacts = Member.objects.all()
        serializer = MemberSerializer(contacts, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = MemberSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



#rest API call
@api_view(['GET', 'POST'])
def MemberListByGroup(request, pk):

    if request.method == 'GET':
        contacts = Member.objects.filter(group_id = pk)
        serializer = MemberSerializer(contacts, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = MemberSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




#notify members in email and text message on phone

#publish message

@permission_required("members.add_member")
@login_required
def NotifyMember_deprecated(request, pk):

    context = {}

    sns = boto3.client('sns')

    topic_arn = 'arn:aws:sns:us-east-1:215632354817:intellidata_notify_topic'

    message = "Start Enrollment"
    messageJSON = json.dumps({"message":message})

    obj = get_object_or_404(Member, pk = pk)

    form = MemberForm(request.POST or None, instance = obj)

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
        return HttpResponseRedirect(reverse("members:all"))

    else:

            # add form dictionary to context
            context["form"] = form

            return render(request, "members/member_form.html", context)


#class for handling built-in API errors
class APIError(Exception):
    """An API Error Exception"""

    def __init__(self, status):
        self.status = status

    def __str__(self):
        return "APIError: status={}".format(self.status)
