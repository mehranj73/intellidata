
from django.conf.urls import url

from . import views

app_name = 'employers'

urlpatterns = [
    url(r"^$", views.ListEmployers.as_view(), name="all"),
    url(r"^ods/history/(?P<pk>\d+)/$", views.ListEmployersHistory, name="history"),
    url(r"^ods/refresh/(?P<pk>\d+)/$", views.RefreshEmployer, name="refresh"),
    url(r"^new/$", views.CreateEmployer.as_view(), name="create"),
    url(r"^bulkupload/$",views.BulkUploadEmployer,name="bulk"),
    url(r"^version/(?P<pk>\d+)/$",views.VersionEmployer, name="version"),
    url(r"^search/$", views.SearchEmployersForm, name="search"),
    url(r"^search/results/$", views.SearchEmployersList.as_view(), name="search_results"),
    url(r"^posts/in/(?P<pk>\d+)/$",views.SingleEmployer.as_view(),name="single"),
    url(r"^update/(?P<pk>\d+)/$",views.UpdateEmployer.as_view(),name="update"),
    url(r"^delete/(?P<pk>\d+)/$",views.DeleteEmployer.as_view(),name="delete"),
    url(r"^rest/employerlist/$",views.EmployerList, name="rest"),
    url(r"^bulkuploadods/$",views.BulkUploadSOR,name="bulksor"),
    url(r"^ods/pull/(?P<pk>\d+)/$",views.BackendPull, name="backendpull"),
    url(r"^employer/error/$",views.ViewEmployerErrorList.as_view(), name='feederrors')

]
