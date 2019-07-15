# JsonWax for Qt
#### Note
December 2017: I've made a big update, which will vastly improve performance. I have to recreate the documentation website, so it may take some weeks (12 months+).

#### Description
JsonWax is a Qt C++ library for handling JSON-documents. It's an alternative to Qt's built-in set of JSON classes, made for Qt 5.7 or later.

The purpose is to shorten your JSON-handling code, and keep your mind on the structure of your document.

Essentially, finding a value in a JSON-document is like finding a file, where the path is a sequence of strings and/or numbers, which here is expressed as a QVariantList.

Instead of extracting objects from objects, you write the whole "directory" in one line, which makes nested JSON-documents easy to manage.

I have created easy-to-use functions for common operations such as: Setting/retrieving/deleting values, loading/saving the document to/from file, copying/moving data from one part of the document to another, and much more.

Furthermore, you can even serialize QObjects and other Qt data types to JSON. Both as readable strings (based on QTextStream), and as a Base64-encoded byte array (based on QDataStream).

Unfortunately this ease of use comes at the price of being slower than QJsonDocument.

#### You may use JsonWax under the terms of any of these licenses:

* GNU General Public License version 2.0 | https://www.gnu.org/licenses/gpl-2.0.html
* GNU General Public License version 3 | https://www.gnu.org/licenses/gpl-3.0.html

### Could still use some more tests.

See documentation on the website: https://doublejim.github.io/
