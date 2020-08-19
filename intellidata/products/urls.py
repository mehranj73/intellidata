from django.conf.urls import url

from . import views

app_name = 'products'

urlpatterns = [
    url(r"^$", views.ListProducts.as_view(), name="all"),
    url(r"^ods/history/(?P<pk>\d+)/$", views.ListProductsHistory, name="history"),
    url(r"^ods/refresh/(?P<pk>\d+)/$", views.RefreshProduct, name="refresh"),
    url(r"^new/$", views.CreateProduct.as_view(), name="create"),
    url(r"^bulkupload/$",views.BulkUploadProduct,name="bulk"),
    url(r"^bulkuploadods/$",views.BulkUploadSOR,name="bulksor"),
    url(r"^version/(?P<pk>\d+)/$",views.VersionProduct, name="version"),
    url(r"^ods/pull/(?P<pk>\d+)/$",views.BackendPull, name="backendpull"),
    url(r"^search/$", views.SearchProductsForm, name="search"),
    url(r"^search/results/$", views.SearchProductsList.as_view(), name="search_results"),
    url(r"^posts/in/(?P<pk>\d+)/$",views.SingleProduct.as_view(),name="single"),
    url(r"^update/(?P<pk>\d+)/$",views.UpdateProduct.as_view(),name="update"),
    url(r"^delete/(?P<pk>\d+)/$",views.DeleteProduct.as_view(),name="delete"),
    url(r"^rest/productlist/$",views.ProductList, name="rest"),
    url(r"^product/error/$",views.ViewProductErrorList.as_view(), name='feederrors')
]
