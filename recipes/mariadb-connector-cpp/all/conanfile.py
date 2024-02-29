from conan import ConanFile
from conan.tools.cmake import CMake, CMakeDeps, cmake_layout, CMakeToolchain
from conan.tools.files import get, collect_libs, replace_in_file, rm, copy
from conan.tools.scm import Version
from conan.errors import ConanInvalidConfiguration
from conan.tools.microsoft import check_min_vs, is_msvc
from conan.tools.env import VirtualBuildEnv
import os

requird_conan_version = ">=1.54.0"

class MariadbConnectorCPPRecipe(ConanFile):
    name = "mariadb-connector-cpp"
    license = "GPL-2.0"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://mariadb.com/docs/server/connect/programming-languages/cpp/"
    description = "A Mariadb database connector for C++ applications that connect to MySQL servers"
    topics = ("mariadb", "connector", "jdbc")
    package_type = "library"
    settings = "os", "compiler", "build_type", "arch"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
        "with_ssl": [False, "openssl", "gnutls", "schannel"],
        "with_curl": [True, False]
        }
    default_options = {
        "shared": False,
        "fPIC": True,
        "with_ssl": "openssl",
        "with_curl": True,
        }

    @property
    def _min_cppstd(self):
        return "11"

    @property
    def _compilers_minimum_version(self):
        return {
            "Visual Studio": "16",
            "msvc": "192",
            "gcc": "9",
            "clang": "6",
        }

    def layout(self):
        cmake_layout(self, src_folder="src")

    def requirements(self):
        self.requires("mariadb-connector-c/3.3.3")
        self.requires("zlib/[>=1.2.10 <2]")
        self.requires("zstd/1.5.5")
        if self.options.with_ssl == "openssl":
            self.requires("openssl/[>=1.1 <4]")

    def source(self):
        get(self, **self.conan_data["sources"][self.version], strip_root=True)

    def validate(self):
        check_min_vs(self, 192)
        if not is_msvc(self):
            minimum_version = self._compilers_minimum_version.get(str(self.settings.compiler), False)
            if minimum_version and Version(self.settings.compiler.version) < minimum_version:
                raise ConanInvalidConfiguration(f"{self.ref} requires C++{self._min_cppstd}, which your compiler does not support.")

        # I dont have a windows computer to test it
        if self.settings.os == "Windows":
            raise ConanInvalidConfiguration(f"{self.ref} doesn't support windows for now")

    def config_options(self):
        if self.settings.os == "Windows":
            self.options.rm_safe("fPIC")

    def configure(self):
        if self.options.shared:
            self.options.rm_safe("fPIC")

    def _package_folder_dep(self, dep):
        return self.dependencies[dep].package_folder.replace("\\", "/")

    def _include_folder_dep(self, dep):
        return self.dependencies[dep].cpp_info.includedirs[0].replace("\\", "/")

    def _lib_folder_dep(self, dep):
        return self.dependencies[dep].cpp_info.libdirs[0].replace("\\", "/")

    def generate(self):
        env = VirtualBuildEnv(self)
        env.generate(scope="build")
        tc = CMakeDeps(self)
        tc.generate()
        tc = CMakeToolchain(self)
        tc.presets_build_environment = env.environment()
        tc.variables["USE_SYSTEM_INSTALLED_LIB"] = True
        tc.variables["WITH_UNIT_TESTS"] = False
        tc.variables["BUILD_SHARED_LIBS"] = self.options.shared
        tc.variables["MARIADB_LINK_DYNAMIC"] = False
        tc.variables["CONC_WITH_UNIT_TESTS"] = False
        tc.variables["WITH_SSL"] = self.options.with_ssl
        tc.variables["WITH_EXTERNAL_ZLIB"] = True
        tc.variables["INSTALL_BINDIR"] = "bin"
        tc.variables["INSTALL_LIBDIR"] = "lib"
        tc.variables["INSTALL_PLUGINDIR"] = os.path.join("lib", "plugin").replace("\\", "/")
        # To install relocatable shared libs on Macos
        tc.cache_variables["CMAKE_POLICY_DEFAULT_CMP0042"] = "NEW"
        tc.generate()

    def _patch_sources(self):
        root_cmake = os.path.join(self.source_folder, "CMakeLists.txt")
        libmysqlclient_dir = self._include_folder_dep("mariadb-connector-c")

        # we need to inject into mariadb-connector-cpp the headers of conan mariadb-connector-c
        replace_in_file(self,
            root_cmake,
            "INCLUDE(SetValueMacro)",
            "INCLUDE(SetValueMacro)\n" + f"INCLUDE_DIRECTORIES({libmysqlclient_dir}/mariadb)"
        )

        # mariadbcpp is using shared lib for unix with this we force be static library
        # this workarround for ld: library 'mariadbclient' not found with conan
        if not self.options.shared:
            replace_in_file(self, root_cmake, "${LIBRARY_NAME} SHARED", "${LIBRARY_NAME} STATIC")


    def build(self):
        self._patch_sources()
        cmake = CMake(self)
        cmake.configure()
        cmake.build()

    def package(self):
        copy(self, "COPYING.LIB", src=self.source_folder, dst=os.path.join(self.package_folder, "licenses"))
        cmake = CMake(self)
        cmake.install()
        rm(self, "INFO_SRC", self.package_folder)
        rm(self, "INFO_BIN", self.package_folder)

    def package_info(self):
        self.cpp_info.set_property("pkg_config_name", "libmariadbcpp")
        self.cpp_info.includedirs.append(os.path.join("include", "mariadb"))
        self.cpp_info.libdirs = ["lib64/debug","lib/debug"] if self.settings.build_type == "Debug" else ["lib64", "lib"]
        self.cpp_info.libs = collect_libs(self)
        if self.settings.os in ["Linux", "FreeBSD", "Macos"]:
            self.cpp_info.system_libs = ["m", "resolv"]
        plugin_dir = os.path.join(self.package_folder, "lib", "plugin").replace("\\", "/")
        self.runenv_info.prepend_path("MARIADB_PLUGIN_DIR", plugin_dir)
